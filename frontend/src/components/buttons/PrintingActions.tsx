import { ApiEndpoints } from '@lib/enums/ApiEndpoints';
import type { ModelType } from '@lib/enums/ModelType';
import { apiUrl } from '@lib/functions/Api';
import type { ApiFormFieldSet } from '@lib/types/Forms';
import { t } from '@lingui/core/macro';
import { IconPrinter, IconReport, IconTags } from '@tabler/icons-react';
import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { api } from '../../App';
import { extractAvailableFields } from '../../functions/forms';
import useDataOutput from '../../hooks/UseDataOutput';
import { useCreateApiFormModal } from '../../hooks/UseForm';
import {
  useGlobalSettingsState,
  useUserSettingsState
} from '../../states/SettingsStates';
import { ActionDropdown } from '../items/ActionDropdown';

export function PrintingActions({
  items,
  hidden,
  enableLabels,
  enableReports,
  modelType
}: {
  items: number[];
  hidden?: boolean;
  enableLabels?: boolean;
  enableReports?: boolean;
  modelType?: ModelType;
}) {
  const userSettings = useUserSettingsState();
  const globalSettings = useGlobalSettingsState();

  const enabled = useMemo(() => items.length > 0, [items]);
  const [pluginKey, setPluginKey] = useState<string>('');

  // **NEW: Toggle states for label content**
  const [includeMPN, setIncludeMPN] = useState<boolean>(true);
  const [includeCategory, setIncludeCategory] = useState<boolean>(true);
  const [includeDescription, setIncludeDescription] = useState<boolean>(true);
  const [includeStockLocation, setIncludeStockLocation] = useState<boolean>(true);
  const [includeQuantity, setIncludeQuantity] = useState<boolean>(true);

  const labelPrintingEnabled = useMemo(() => {
    return enableLabels && globalSettings.isSet('LABEL_ENABLE');
  }, [enableLabels, globalSettings]);

  const reportPrintingEnabled = useMemo(() => {
    return enableReports && globalSettings.isSet('REPORT_ENABLE');
  }, [enableReports, globalSettings]);

  const [labelId, setLabelId] = useState<number | undefined>(undefined);
  const [reportId, setReportId] = useState<number | undefined>(undefined);

  const labelProgress = useDataOutput({
    title: t`Printing Labels`,
    id: labelId
  });

  const reportProgress = useDataOutput({
    title: t`Printing Reports`,
    id: reportId
  });

  // Fetch available printing fields via OPTIONS request
  const printingFields = useQuery({
    enabled: labelPrintingEnabled,
    queryKey: ['printingFields', modelType, pluginKey],
    gcTime: 500,
    queryFn: () =>
      api
        .options(apiUrl(ApiEndpoints.label_print), {
          params: {
            plugin: pluginKey || undefined
          }
        })
        .then((response: any) => {
          return extractAvailableFields(response, 'POST') || {};
        })
  });

  const labelFields: ApiFormFieldSet = useMemo(() => {
    const fields: ApiFormFieldSet = printingFields.data || {};

    // Override field values
    fields.template = {
      ...fields.template,
      filters: {
        enabled: true,
        model_type: modelType,
        items: items.join(',')
      }
    };

    fields.items = {
      ...fields.items,
      value: items,
      hidden: true
    };

    fields['plugin'] = {
      ...fields['plugin'],
      value: userSettings.getSetting('LABEL_DEFAULT_PRINTER'),
      filters: {
        active: true,
        mixin: 'labels'
      },
      onValueChange: (value: string, record?: any) => {
        if (record?.key && record?.key != pluginKey) {
          setPluginKey(record.key);
        }
      }
    };

    // **NEW: Add toggle fields to the form**
    fields.include_mpn = {
      field_type: 'boolean',
      label: t`Include MPN`,

      value: includeMPN,
      onValueChange: (value: boolean) => setIncludeMPN(value)
    };

    fields.include_category = {
      field_type: 'boolean',
      label: t`Include Category`,

      value: includeCategory,
      onValueChange: (value: boolean) => setIncludeCategory(value)
    };

    fields.include_description = {
      field_type: 'boolean',
      label: t`Include Description`,

      value: includeDescription,
      onValueChange: (value: boolean) => setIncludeDescription(value)
    };

    fields.include_stock_location = {
      field_type: 'boolean',
      label: t`Include Stock Location`,

      value: includeStockLocation,
      onValueChange: (value: boolean) => setIncludeStockLocation(value)
    };

    fields.include_quantity = {
      field_type: 'boolean',
      label: t`Include Quantity`,

      value: includeQuantity,
      onValueChange: (value: boolean) => setIncludeQuantity(value)
    };

    return fields;
  }, [printingFields.data, items, includeMPN, includeCategory, includeDescription, includeStockLocation, includeQuantity]);

  const labelModal = useCreateApiFormModal({
    url: apiUrl(ApiEndpoints.label_print),
    title: t`Print Label`,
    fields: labelFields, // This already contains the toggle values
    timeout: 50000,
    onClose: () => {
      setPluginKey('');
    },
    submitText: t`Print`,
    successMessage: null,
    onFormSuccess: (response: any) => {
      // Log the toggle values that were submitted
      console.log('Label print request submitted with toggle values:', {
        include_mpn: includeMPN,
        include_category: includeCategory,
        include_description: includeDescription,
        include_stock_location: includeStockLocation,
        include_quantity: includeQuantity
      });
      console.log('API response:', response);
      setPluginKey('');
      setLabelId(response.pk);
    }
  });

  const reportModal = useCreateApiFormModal({
    title: t`Print Report`,
    url: apiUrl(ApiEndpoints.report_print),
    timeout: 5000,
    fields: {
      template: {
        filters: {
          enabled: true,
          model_type: modelType,
          items: items.join(',')
        }
      },
      items: {
        hidden: true,
        value: items
      }
    },
    submitText: t`Print`,
    successMessage: null,
    onFormSuccess: (response: any) => {
      setReportId(response.pk);
    }
  });

  if (!modelType) {
    return null;
  }

  if (!labelPrintingEnabled && !reportPrintingEnabled) {
    return null;
  }

  return (
    !hidden && (
      <>
        {reportModal.modal}
        {labelModal.modal}
        <ActionDropdown
          tooltip={t`Printing Actions`}
          icon={<IconPrinter />}
          disabled={!enabled}
          actions={[
            {
              name: t`Print Labels`,
              icon: <IconTags />,
              onClick: () => labelModal.open(),
              hidden: !labelPrintingEnabled
            },
            {
              name: t`Print Reports`,
              icon: <IconReport />,
              onClick: () => reportModal.open(),
              hidden: !reportPrintingEnabled
            }
          ]}
        />
      </>
    )
  );
}