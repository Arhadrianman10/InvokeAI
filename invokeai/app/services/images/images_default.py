import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import List, Optional
from uuid import uuid4

from PIL.Image import Image as PILImageType
from tqdm import tqdm

from invokeai.app.invocations.fields import MetadataField
from invokeai.app.services.image_files.image_files_common import (
    ImageFileDeleteException,
    ImageFileNotFoundException,
    ImageFileSaveException,
)
from invokeai.app.services.image_records.image_records_common import (
    ImageCategory,
    ImageRecord,
    ImageRecordChanges,
    ImageRecordDeleteException,
    ImageRecordNotFoundException,
    ImageRecordSaveException,
    InvalidImageCategoryException,
    InvalidOriginException,
    ResourceOrigin,
)
from invokeai.app.services.images.images_base import ImageServiceABC
from invokeai.app.services.images.images_common import ImageBulkUploadData, ImageDTO, image_record_to_dto
from invokeai.app.services.invoker import Invoker
from invokeai.app.services.shared.pagination import OffsetPaginatedResults
from invokeai.app.services.shared.sqlite.sqlite_common import SQLiteDirection


class ImageService(ImageServiceABC):
    __invoker: Invoker

    def start(self, invoker: Invoker) -> None:
        self.__invoker = invoker

    def create(
        self,
        image: PILImageType,
        image_origin: ResourceOrigin,
        image_category: ImageCategory,
        node_id: Optional[str] = None,
        session_id: Optional[str] = None,
        board_id: Optional[str] = None,
        is_intermediate: Optional[bool] = False,
        metadata: Optional[str] = None,
        workflow: Optional[str] = None,
        graph: Optional[str] = None,
    ) -> ImageDTO:
        if image_origin not in ResourceOrigin:
            raise InvalidOriginException

        if image_category not in ImageCategory:
            raise InvalidImageCategoryException

        image_name = self.__invoker.services.names.create_image_name()

        (width, height) = image.size

        try:
            # TODO: Consider using a transaction here to ensure consistency between storage and database
            self.__invoker.services.image_records.save(
                # Non-nullable fields
                image_name=image_name,
                image_origin=image_origin,
                image_category=image_category,
                width=width,
                height=height,
                has_workflow=workflow is not None or graph is not None,
                # Meta fields
                is_intermediate=is_intermediate,
                # Nullable fields
                node_id=node_id,
                metadata=metadata,
                session_id=session_id,
            )
            if board_id is not None:
                try:
                    self.__invoker.services.board_image_records.add_image_to_board(
                        board_id=board_id, image_name=image_name
                    )
                except Exception as e:
                    self.__invoker.services.logger.warn(f"Failed to add image to board {board_id}: {str(e)}")
            self.__invoker.services.image_files.save(
                image_name=image_name, image=image, metadata=metadata, workflow=workflow, graph=graph
            )
            image_dto = self.get_dto(image_name)

            self._on_changed(image_dto)
            return image_dto
        except ImageRecordSaveException:
            self.__invoker.services.logger.error("Failed to save image record")
            raise
        except ImageFileSaveException:
            self.__invoker.services.logger.error("Failed to save image file")
            raise
        except Exception as e:
            self.__invoker.services.logger.error(f"Problem saving image record and file: {str(e)}")
            raise e

    def create_many(self, upload_data_list: List[ImageBulkUploadData]) -> None:
        total_images = len(upload_data_list)
        processed_counter = 0  # Local counter
        images_DTOs: list[ImageDTO] = []  # Collect ImageDTOs for successful uploads
        progress_lock = Lock()
        bulk_upload_id = uuid4().hex

        self.__invoker.services.events.emit_bulk_upload_started(
            bulk_upload_id=bulk_upload_id,
            total=total_images,
        )

        def process_and_save_image(image_data: ImageBulkUploadData):
            nonlocal processed_counter  # refer to the counter in the enclosing scope
            try:
                # processing and saving each image
                width, height = image_data.image.size
                image_data.width = width
                image_data.height = height
                image_name = self.__invoker.services.names.create_image_name()
                image_data.image_name = image_name
                self.__invoker.services.image_records.save(
                    image_name=image_data.image_name,
                    image_origin=ResourceOrigin.EXTERNAL,
                    image_category=ImageCategory.USER,
                    width=image_data.width,
                    height=image_data.height,
                    has_workflow=image_data.workflow is not None or image_data.graph is not None,
                    is_intermediate=False,
                    metadata=image_data.metadata,
                )

                if image_data.board_id is not None:
                    self.__invoker.services.board_image_records.add_image_to_board(
                        board_id=image_data.board_id, image_name=image_data.image_name
                    )

                self.__invoker.services.image_files.save(
                    image_name=image_data.image_name,
                    image=image_data.image,
                    metadata=image_data.metadata,
                    workflow=image_data.workflow,
                    graph=image_data.graph,
                )

                image_dto = self.get_dto(image_data.image_name)
                self._on_changed(image_dto)

                with progress_lock:
                    processed_counter += 1

                return image_dto
            except ImageRecordSaveException:
                self.__invoker.services.logger.error("Failed to save image record")
                raise
            except ImageFileSaveException:
                self.__invoker.services.logger.error("Failed to save image file")
                raise
            except Exception as e:
                self.__invoker.services.logger.error(f"Problem processing and saving image: {str(e)}")
                raise e

        # Determine the number of available CPU cores
        num_cores = os.cpu_count() or 1
        num_workers = max(1, num_cores - 1)

        # Initialize tqdm progress bar
        pbar = tqdm(total=total_images, desc="Processing Images", unit="images", colour="green")

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(process_and_save_image, image) for image in upload_data_list]
            for future in as_completed(futures):
                try:
                    image_DTO = future.result()
                    images_DTOs.append(image_DTO)
                    pbar.update(1)  # Update progress bar

                    self.__invoker.services.events.emit_bulk_upload_progress(
                        bulk_upload_id=bulk_upload_id,
                        completed=processed_counter,
                        total=total_images,
                        image_DTO=image_DTO,
                    )
                except Exception as e:
                    self.__invoker.services.logger.error(f"Error in processing image: {str(e)}")
                    self.__invoker.services.events.emit_bulk_upload_error(bulk_upload_id=bulk_upload_id, error=str(e))

        pbar.close()
        self.__invoker.services.events.emit_bulk_upload_complete(bulk_upload_id=bulk_upload_id, total=len(images_DTOs))

    def update(
        self,
        image_name: str,
        changes: ImageRecordChanges,
    ) -> ImageDTO:
        try:
            self.__invoker.services.image_records.update(image_name, changes)
            image_dto = self.get_dto(image_name)
            self._on_changed(image_dto)
            return image_dto
        except ImageRecordSaveException:
            self.__invoker.services.logger.error("Failed to update image record")
            raise
        except Exception as e:
            self.__invoker.services.logger.error("Problem updating image record")
            raise e

    def get_pil_image(self, image_name: str) -> PILImageType:
        try:
            return self.__invoker.services.image_files.get(image_name)
        except ImageFileNotFoundException:
            self.__invoker.services.logger.error("Failed to get image file")
            raise
        except Exception as e:
            self.__invoker.services.logger.error("Problem getting image file")
            raise e

    def get_record(self, image_name: str) -> ImageRecord:
        try:
            return self.__invoker.services.image_records.get(image_name)
        except ImageRecordNotFoundException:
            self.__invoker.services.logger.error("Image record not found")
            raise
        except Exception as e:
            self.__invoker.services.logger.error("Problem getting image record")
            raise e

    def get_dto(self, image_name: str) -> ImageDTO:
        try:
            image_record = self.__invoker.services.image_records.get(image_name)

            image_dto = image_record_to_dto(
                image_record=image_record,
                image_url=self.__invoker.services.urls.get_image_url(image_name),
                thumbnail_url=self.__invoker.services.urls.get_image_url(image_name, True),
                board_id=self.__invoker.services.board_image_records.get_board_for_image(image_name),
            )

            return image_dto
        except ImageRecordNotFoundException:
            self.__invoker.services.logger.error("Image record not found")
            raise
        except Exception as e:
            self.__invoker.services.logger.error("Problem getting image DTO")
            raise e

    def get_metadata(self, image_name: str) -> Optional[MetadataField]:
        try:
            return self.__invoker.services.image_records.get_metadata(image_name)
        except ImageRecordNotFoundException:
            self.__invoker.services.logger.error("Image record not found")
            raise
        except Exception as e:
            self.__invoker.services.logger.error("Problem getting image metadata")
            raise e

    def get_workflow(self, image_name: str) -> Optional[str]:
        try:
            return self.__invoker.services.image_files.get_workflow(image_name)
        except ImageFileNotFoundException:
            self.__invoker.services.logger.error("Image file not found")
            raise
        except Exception:
            self.__invoker.services.logger.error("Problem getting image workflow")
            raise

    def get_graph(self, image_name: str) -> Optional[str]:
        try:
            return self.__invoker.services.image_files.get_graph(image_name)
        except ImageFileNotFoundException:
            self.__invoker.services.logger.error("Image file not found")
            raise
        except Exception:
            self.__invoker.services.logger.error("Problem getting image graph")
            raise

    def get_path(self, image_name: str, thumbnail: bool = False) -> str:
        try:
            return str(self.__invoker.services.image_files.get_path(image_name, thumbnail))
        except Exception as e:
            self.__invoker.services.logger.error("Problem getting image path")
            raise e

    def validate_path(self, path: str) -> bool:
        try:
            return self.__invoker.services.image_files.validate_path(path)
        except Exception as e:
            self.__invoker.services.logger.error("Problem validating image path")
            raise e

    def get_url(self, image_name: str, thumbnail: bool = False) -> str:
        try:
            return self.__invoker.services.urls.get_image_url(image_name, thumbnail)
        except Exception as e:
            self.__invoker.services.logger.error("Problem getting image path")
            raise e

    def get_many(
        self,
        offset: int = 0,
        limit: int = 10,
        starred_first: bool = True,
        order_dir: SQLiteDirection = SQLiteDirection.Descending,
        image_origin: Optional[ResourceOrigin] = None,
        categories: Optional[list[ImageCategory]] = None,
        is_intermediate: Optional[bool] = None,
        board_id: Optional[str] = None,
        search_term: Optional[str] = None,
    ) -> OffsetPaginatedResults[ImageDTO]:
        try:
            results = self.__invoker.services.image_records.get_many(
                offset,
                limit,
                starred_first,
                order_dir,
                image_origin,
                categories,
                is_intermediate,
                board_id,
                search_term,
            )

            image_dtos = [
                image_record_to_dto(
                    image_record=r,
                    image_url=self.__invoker.services.urls.get_image_url(r.image_name),
                    thumbnail_url=self.__invoker.services.urls.get_image_url(r.image_name, True),
                    board_id=self.__invoker.services.board_image_records.get_board_for_image(r.image_name),
                )
                for r in results.items
            ]

            return OffsetPaginatedResults[ImageDTO](
                items=image_dtos,
                offset=results.offset,
                limit=results.limit,
                total=results.total,
            )
        except Exception as e:
            self.__invoker.services.logger.error("Problem getting paginated image DTOs")
            raise e

    def delete(self, image_name: str):
        try:
            self.__invoker.services.image_files.delete(image_name)
            self.__invoker.services.image_records.delete(image_name)
            self._on_deleted(image_name)
        except ImageRecordDeleteException:
            self.__invoker.services.logger.error("Failed to delete image record")
            raise
        except ImageFileDeleteException:
            self.__invoker.services.logger.error("Failed to delete image file")
            raise
        except Exception as e:
            self.__invoker.services.logger.error("Problem deleting image record and file")
            raise e

    def delete_images_on_board(self, board_id: str):
        try:
            image_names = self.__invoker.services.board_image_records.get_all_board_image_names_for_board(board_id)
            for image_name in image_names:
                self.__invoker.services.image_files.delete(image_name)
            self.__invoker.services.image_records.delete_many(image_names)
            for image_name in image_names:
                self._on_deleted(image_name)
        except ImageRecordDeleteException:
            self.__invoker.services.logger.error("Failed to delete image records")
            raise
        except ImageFileDeleteException:
            self.__invoker.services.logger.error("Failed to delete image files")
            raise
        except Exception as e:
            self.__invoker.services.logger.error("Problem deleting image records and files")
            raise e

    def delete_intermediates(self) -> int:
        try:
            image_names = self.__invoker.services.image_records.delete_intermediates()
            count = len(image_names)
            for image_name in image_names:
                self.__invoker.services.image_files.delete(image_name)
                self._on_deleted(image_name)
            return count
        except ImageRecordDeleteException:
            self.__invoker.services.logger.error("Failed to delete image records")
            raise
        except ImageFileDeleteException:
            self.__invoker.services.logger.error("Failed to delete image files")
            raise
        except Exception as e:
            self.__invoker.services.logger.error("Problem deleting image records and files")
            raise e

    def get_intermediates_count(self) -> int:
        try:
            return self.__invoker.services.image_records.get_intermediates_count()
        except Exception as e:
            self.__invoker.services.logger.error("Problem getting intermediates count")
            raise e
