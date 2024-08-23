import { Badge } from '@invoke-ai/ui-library';
import { useAppSelector } from 'app/store/storeHooks';
import { useEntityIdentifierContext } from 'features/controlLayers/contexts/EntityIdentifierContext';
import { selectRegionalGuidanceEntityOrThrow } from 'features/controlLayers/store/regionsReducers';
import { memo } from 'react';
import { useTranslation } from 'react-i18next';

export const RegionalGuidanceBadges = memo(() => {
  const { id } = useEntityIdentifierContext();
  const { t } = useTranslation();
  const autoNegative = useAppSelector((s) => selectRegionalGuidanceEntityOrThrow(s.canvasV2, id).autoNegative);

  return (
    <>
      {autoNegative && (
        <Badge color="base.300" bg="transparent" borderWidth={1} userSelect="none">
          {t('controlLayers.autoNegative')}
        </Badge>
      )}
    </>
  );
});

RegionalGuidanceBadges.displayName = 'RegionalGuidanceBadges';
