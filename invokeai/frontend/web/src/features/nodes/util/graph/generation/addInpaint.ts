import type { CanvasManager } from 'features/controlLayers/konva/CanvasManager';
import type { CanvasV2State, Dimensions } from 'features/controlLayers/store/types';
import type { Graph } from 'features/nodes/util/graph/generation/Graph';
import type { ParameterPrecision } from 'features/parameters/types/parameterSchemas';
import { isEqual } from 'lodash-es';
import type { Invocation } from 'services/api/types';

export const addInpaint = async (
  g: Graph,
  manager: CanvasManager,
  l2i: Invocation<'l2i'>,
  denoise: Invocation<'denoise_latents'>,
  vaeSource: Invocation<'main_model_loader' | 'sdxl_model_loader' | 'seamless' | 'vae_loader'>,
  modelLoader: Invocation<'main_model_loader' | 'sdxl_model_loader'>,
  originalSize: Dimensions,
  scaledSize: Dimensions,
  bbox: CanvasV2State['bbox'],
  compositing: CanvasV2State['compositing'],
  denoising_start: number,
  vaePrecision: ParameterPrecision
): Promise<Invocation<'canvas_v2_mask_and_crop'>> => {
  denoise.denoising_start = denoising_start;

  const initialImage = await manager.getCompositeRasterLayerImageDTO(bbox.rect);
  const maskImage = await manager.getCompositeInpaintMaskImageDTO(bbox.rect);

  if (!isEqual(scaledSize, originalSize)) {
    // Scale before processing requires some resizing
    const i2l = g.addNode({ id: 'i2l', type: 'i2l' });
    const resizeImageToScaledSize = g.addNode({
      id: 'resize_image_to_scaled_size',
      type: 'img_resize',
      image: { image_name: initialImage.image_name },
      ...scaledSize,
    });
    const alphaToMask = g.addNode({
      id: 'alpha_to_mask',
      type: 'tomask',
      image: { image_name: maskImage.image_name },
      invert: true,
    });
    const resizeMaskToScaledSize = g.addNode({
      id: 'resize_mask_to_scaled_size',
      type: 'img_resize',
      ...scaledSize,
    });
    const resizeImageToOriginalSize = g.addNode({
      id: 'resize_image_to_original_size',
      type: 'img_resize',
      ...originalSize,
    });
    const resizeMaskToOriginalSize = g.addNode({
      id: 'resize_mask_to_original_size',
      type: 'img_resize',
      ...originalSize,
    });
    const createGradientMask = g.addNode({
      id: 'create_gradient_mask',
      type: 'create_gradient_mask',
      coherence_mode: compositing.canvasCoherenceMode,
      minimum_denoise: compositing.canvasCoherenceMinDenoise,
      edge_radius: compositing.canvasCoherenceEdgeSize,
      fp32: vaePrecision === 'fp32',
    });
    const canvasPasteBack = g.addNode({
      id: 'canvas_v2_mask_and_crop',
      type: 'canvas_v2_mask_and_crop',
      mask_blur: compositing.maskBlur,
    });

    // Resize initial image and mask to scaled size, feed into to gradient mask
    g.addEdge(alphaToMask, 'image', resizeMaskToScaledSize, 'image');
    g.addEdge(resizeImageToScaledSize, 'image', i2l, 'image');
    g.addEdge(i2l, 'latents', denoise, 'latents');
    g.addEdge(vaeSource, 'vae', i2l, 'vae');

    g.addEdge(vaeSource, 'vae', createGradientMask, 'vae');
    g.addEdge(modelLoader, 'unet', createGradientMask, 'unet');
    g.addEdge(resizeImageToScaledSize, 'image', createGradientMask, 'image');
    g.addEdge(resizeMaskToScaledSize, 'image', createGradientMask, 'mask');

    g.addEdge(createGradientMask, 'denoise_mask', denoise, 'denoise_mask');

    // After denoising, resize the image and mask back to original size
    g.addEdge(l2i, 'image', resizeImageToOriginalSize, 'image');
    g.addEdge(createGradientMask, 'expanded_mask_area', resizeMaskToOriginalSize, 'image');

    // Finally, paste the generated masked image back onto the original image
    g.addEdge(resizeImageToOriginalSize, 'image', canvasPasteBack, 'image');
    g.addEdge(resizeMaskToOriginalSize, 'image', canvasPasteBack, 'mask');

    return canvasPasteBack;
  } else {
    // No scale before processing, much simpler
    const i2l = g.addNode({ id: 'i2l', type: 'i2l', image: { image_name: initialImage.image_name } });
    const alphaToMask = g.addNode({
      id: 'alpha_to_mask',
      type: 'tomask',
      image: { image_name: maskImage.image_name },
      invert: true,
    });
    const createGradientMask = g.addNode({
      id: 'create_gradient_mask',
      type: 'create_gradient_mask',
      coherence_mode: compositing.canvasCoherenceMode,
      minimum_denoise: compositing.canvasCoherenceMinDenoise,
      edge_radius: compositing.canvasCoherenceEdgeSize,
      fp32: vaePrecision === 'fp32',
      image: { image_name: initialImage.image_name },
    });
    const canvasPasteBack = g.addNode({
      id: 'canvas_v2_mask_and_crop',
      type: 'canvas_v2_mask_and_crop',
      mask_blur: compositing.maskBlur,
    });
    g.addEdge(alphaToMask, 'image', createGradientMask, 'mask');
    g.addEdge(i2l, 'latents', denoise, 'latents');
    g.addEdge(vaeSource, 'vae', i2l, 'vae');
    g.addEdge(vaeSource, 'vae', createGradientMask, 'vae');
    g.addEdge(modelLoader, 'unet', createGradientMask, 'unet');
    g.addEdge(createGradientMask, 'denoise_mask', denoise, 'denoise_mask');
    g.addEdge(createGradientMask, 'expanded_mask_area', canvasPasteBack, 'mask');

    g.addEdge(l2i, 'image', canvasPasteBack, 'image');

    return canvasPasteBack;
  }
};
