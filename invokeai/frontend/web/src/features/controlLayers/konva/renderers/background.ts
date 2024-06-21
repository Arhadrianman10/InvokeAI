import { getArbitraryBaseColor } from '@invoke-ai/ui-library';
import { BACKGROUND_LAYER_ID } from 'features/controlLayers/konva/naming';
import type { KonvaNodeManager } from 'features/controlLayers/konva/nodeManager';
import Konva from 'konva';

const baseGridLineColor = getArbitraryBaseColor(27);
const fineGridLineColor = getArbitraryBaseColor(18);

/**
 * Gets the grid spacing. The value depends on the stage scale - at higher scales, the grid spacing is smaller.
 * @param scale The stage scale
 * @returns The grid spacing based on the stage scale
 */
const getGridSpacing = (scale: number): number => {
  if (scale >= 2) {
    return 8;
  }
  if (scale >= 1 && scale < 2) {
    return 16;
  }
  if (scale >= 0.5 && scale < 1) {
    return 32;
  }
  if (scale >= 0.25 && scale < 0.5) {
    return 64;
  }
  if (scale >= 0.125 && scale < 0.25) {
    return 128;
  }
  return 256;
};

/**
 * Creates the background konva layer.
 * @returns The background konva layer
 */
export const createBackgroundLayer = (): Konva.Layer => new Konva.Layer({ id: BACKGROUND_LAYER_ID, listening: false });

/**
 * Gets a render function for the background layer.
 * @param arg.manager The konva node manager
 * @returns A function to render the background grid
 */
export const getRenderBackground = (arg: { manager: KonvaNodeManager }) => (): void => {
  const { manager } = arg;
  const background = manager.background.layer;
  background.zIndex(0);
  const scale = manager.stage.scaleX();
  const gridSpacing = getGridSpacing(scale);
  const x = manager.stage.x();
  const y = manager.stage.y();
  const width = manager.stage.width();
  const height = manager.stage.height();
  const stageRect = {
    x1: 0,
    y1: 0,
    x2: width,
    y2: height,
  };

  const gridOffset = {
    x: Math.ceil(x / scale / gridSpacing) * gridSpacing,
    y: Math.ceil(y / scale / gridSpacing) * gridSpacing,
  };

  const gridRect = {
    x1: -gridOffset.x,
    y1: -gridOffset.y,
    x2: width / scale - gridOffset.x + gridSpacing,
    y2: height / scale - gridOffset.y + gridSpacing,
  };

  const gridFullRect = {
    x1: Math.min(stageRect.x1, gridRect.x1),
    y1: Math.min(stageRect.y1, gridRect.y1),
    x2: Math.max(stageRect.x2, gridRect.x2),
    y2: Math.max(stageRect.y2, gridRect.y2),
  };

  // find the x & y size of the grid
  const xSize = gridFullRect.x2 - gridFullRect.x1;
  const ySize = gridFullRect.y2 - gridFullRect.y1;
  // compute the number of steps required on each axis.
  const xSteps = Math.round(xSize / gridSpacing) + 1;
  const ySteps = Math.round(ySize / gridSpacing) + 1;

  const strokeWidth = 1 / scale;
  let _x = 0;
  let _y = 0;

  background.destroyChildren();

  for (let i = 0; i < xSteps; i++) {
    _x = gridFullRect.x1 + i * gridSpacing;
    background.add(
      new Konva.Line({
        x: _x,
        y: gridFullRect.y1,
        points: [0, 0, 0, ySize],
        stroke: _x % 64 ? fineGridLineColor : baseGridLineColor,
        strokeWidth,
        listening: false,
      })
    );
  }
  for (let i = 0; i < ySteps; i++) {
    _y = gridFullRect.y1 + i * gridSpacing;
    background.add(
      new Konva.Line({
        x: gridFullRect.x1,
        y: _y,
        points: [0, 0, xSize, 0],
        stroke: _y % 64 ? fineGridLineColor : baseGridLineColor,
        strokeWidth,
        listening: false,
      })
    );
  }
};
