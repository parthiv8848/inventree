import { t } from '@lingui/core/macro';
import { Alert, Group, Stack, Text } from '@mantine/core';
import { showNotification } from '@mantine/notifications';
import {
  IconArrowRight,
  IconCircleCheck,
  IconFileArrowLeft,
  IconLock,
  IconSwitch3
} from '@tabler/icons-react';
import { type ReactNode, useCallback, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { ApiEndpoints } from '@lib/enums/ApiEndpoints';
import { ModelType } from '@lib/enums/ModelType';
import { UserRoles } from '@lib/enums/Roles';
import { apiUrl } from '@lib/functions/Api';
import { navigateToLink } from '@lib/functions/Navigation';
import type { TableFilter } from '@lib/types/Filters';
import { ActionButton } from '../../components/buttons/ActionButton';
import { AddItemButton } from '../../components/buttons/AddItemButton';
import { YesNoButton } from '../../components/buttons/YesNoButton';
import { Thumbnail } from '../../components/images/Thumbnail';
import ImporterDrawer from '../../components/importer/ImporterDrawer';
import { RenderPart } from '../../components/render/Part';
import { useApi } from '../../contexts/ApiContext';
import { formatDecimal, formatPriceRange } from '../../defaults/formatters';
import { bomItemFields, useEditBomSubstitutesForm } from '../../forms/BomForms';
import { dataImporterSessionFields } from '../../forms/ImporterForms';
import {
  useApiFormModal,
  useCreateApiFormModal,
  useDeleteApiFormModal,
  useEditApiFormModal
} from '../../hooks/UseForm';
import { useTable } from '../../hooks/UseTable';
import { useUserState } from '../../states/UserState';
import type { TableColumn } from '../Column';
import {
  BooleanColumn,
  DescriptionColumn,
  NoteColumn,
  ReferenceColumn
} from '../ColumnRenderers';
import { InvenTreeTable } from '../InvenTreeTable';
import { type RowAction, RowDeleteAction, RowEditAction } from '../RowActions';
import { TableHoverCard } from '../TableHoverCard';
import { useEffect } from 'react';
import { NumberInput } from '@mantine/core';

interface BomItemRecord {
  pk: number;
  part: number;
  sub_part_detail: any;
  quantity: number;
  pricing_max: number;
  pricing_max_total: number;
  available_stock: number;
  available_substitute_stock?: number;
  available_variant_stock?: number;
  allow_variants?: boolean;
  substitutes?: any[];
  validated?: boolean;
  [key: string]: any;
}

// Calculate the total stock quantity available for a given BomItem
function availableStockQuantity(record: any): number {
  // Base availability
  let available: number = record.available_stock;

  // Add in available substitute stock
  available += record?.available_substitute_stock ?? 0;

  // Add in variant stock
  if (record.allow_variants) {
    available += record?.available_variant_stock ?? 0;
  }

  return available;
}

export function BomTable({
  partId,
  partLocked,
  params = {}
}: Readonly<{
  partId: number;
  partLocked?: boolean;
  params?: any;
}>) {
  const api = useApi();
  const user = useUserState();
  const table = useTable('bom');
  const navigate = useNavigate();
  // console.log('User Permissions:', user.permissions);
  // console.log('User Roles:', user);

  const [importOpened, setImportOpened] = useState<boolean>(false);

  const [selectedSession, setSelectedSession] = useState<number | undefined>(
    undefined
  );
const [totalBomCost, setTotalBomCost] = useState<number>(0);
const [editableRecords, setEditableRecords] = useState<any[]>([]);
const [isEditing, setIsEditing] = useState<boolean>(false);
const [assemblyQuantity, setAssemblyQuantity] = useState<number>(1);
const [assemblyCost, setAssemblyCost] = useState<number>(0);
const [additionalCost, setAdditionalCost] = useState<number>(0);
const [exchangeRate, setExchangeRate] = useState<number>(83.0); // default 1 USD = 83 INR
const [finalTotalINR, setFinalTotalINR] = useState<number>(0);

useEffect(() => {
  async function fetchExchangeRate() {
    try {
      const response = await fetch('https://open.er-api.com/v6/latest/USD');
      const data = await response.json();

      if (data?.result === 'success' && data?.rates?.INR) {
        setExchangeRate(data.rates.INR);
      } else {
        console.warn('Could not get INR rate, using default.');
      }
    } catch (error) {
      console.error('Failed to fetch exchange rate:', error);
    }
  }

  fetchExchangeRate();
}, []);

const calculateFinalCost = useCallback(() => {
  const totalAssemblyCost = assemblyQuantity * assemblyCost;
  const totalBomCostUSD = totalBomCost * assemblyQuantity;
  const totalBomCostINR = totalBomCostUSD * exchangeRate;
  const finalTotal = totalAssemblyCost + totalBomCostINR + additionalCost;
  setFinalTotalINR(finalTotal);
}, [assemblyQuantity, assemblyCost, totalBomCost, exchangeRate, additionalCost]);

useEffect(() => {
  calculateFinalCost();
}, [calculateFinalCost]);

useEffect(() => {
  if (table.records && table.records.length > 0) {
    // Safely sum all 'pricing_max_total' values
    const total = table.records.reduce(
      (acc: number, record: any) =>
        acc + (parseFloat(record.pricing_max_total) || 0),
      0
    );

    setTotalBomCost(total);
  } else {
    setTotalBomCost(0);
  }
}, [table.records]);

useEffect(() => {
  if (table.records && table.records.length > 0) {
    // Create a local editable copy
    const data = table.records.map((r: any) => ({
      ...r,
      editable_qty: r.quantity || 0,
      editable_unit_price: r.pricing_max || 0,
      editable_total_price: (r.quantity || 0) * (r.pricing_max || 0)
    }));

    setEditableRecords(data);

    // Calculate initial total BOM cost
    const total = data.reduce((acc, r) => acc + r.editable_total_price, 0);
    setTotalBomCost(total);
  }
}, [table.records]);

const handleValueChange = (index: number, field: 'editable_qty' | 'editable_unit_price', value: number) => {
  const updated = [...editableRecords];
  updated[index][field] = value;

  // Recalculate total for that row
  const qty = parseFloat(updated[index].editable_qty) || 0;
  const price = parseFloat(updated[index].editable_unit_price) || 0;
  updated[index].editable_total_price = qty * price;

  // Recalculate total BOM cost
  const total = updated.reduce((acc, r) => acc + (r.editable_total_price || 0), 0);
  setTotalBomCost(total);

  setEditableRecords(updated);
};

const toggleEditMode = () => {
  if (!isEditing) {
    // When enabling edit mode: copy data to editableRecords
    if (table.records && table.records.length > 0) {
      const data = table.records.map((r: any) => ({
        ...r,
        editable_qty: r.quantity || 0,
        editable_unit_price: r.pricing_max || 0,
        editable_total_price: (r.quantity || 0) * (r.pricing_max || 0)
      }));
      setEditableRecords(data);

      const total = data.reduce((acc, r) => acc + r.editable_total_price, 0);
      setTotalBomCost(total);
    }
  } else {
    // When disabling edit mode: revert back to original data
    if (table.records && table.records.length > 0) {
      const originalData = table.records.map((r: any) => ({
        ...r,
        editable_qty: r.quantity || 0,
        editable_unit_price: r.pricing_max || 0,
        editable_total_price: (r.quantity || 0) * (r.pricing_max || 0)
      }));
      setEditableRecords(originalData);

      const total = originalData.reduce((acc, r) => acc + r.editable_total_price, 0);
      setTotalBomCost(total);
    }
  }

  setIsEditing(!isEditing);
};

  const tableColumns: TableColumn[] = useMemo(() => {
    return [
      {
        accessor: 'sub_part',
        switchable: false,
        sortable: true,
        render: (record) => {
          const part = record.sub_part_detail;
          const extra = [];

          if (record.part != partId) {
            extra.push(
              <Text key='different-parent'>{t`This BOM item is defined for a different parent`}</Text>
            );
          }

          return (
            part && (
              <TableHoverCard
                value={
                  <Thumbnail
                    src={part.thumbnail || part.image}
                    alt={part.description}
                    text={part.full_name}
                  />
                }
                extra={extra}
                title={t`Part Information`}
              />
            )
          );
        }
      },
      {
        accessor: 'sub_part_detail.IPN',
        title: t`IPN`,
        sortable: true
      },
      DescriptionColumn({
        accessor: 'sub_part_detail.description'
      }),
      ReferenceColumn({
        switchable: true
      }),
      {
        accessor: 'quantity',
        title: t`Quantity`,
        render: (_record: any, index?: number) =>
          isEditing ? (
            <NumberInput
              value={editableRecords[index ?? 0]?.editable_qty ?? 0}
              min={0}
              step={1}
              onChange={(val) => handleValueChange(index ?? 0, 'editable_qty', Number(val) || 0)}
              size="xs"
              w={80}
            />
          ) : (
            <Text>{editableRecords[index ?? 0]?.editable_qty ?? 0}</Text>
          )
      },
      {
        accessor: 'substitutes',
        defaultVisible: false,
        render: (row) => {
          const substitutes = row.substitutes ?? [];

          return substitutes.length > 0 ? (
            <TableHoverCard
              value={<Text>{substitutes.length}</Text>}
              title={t`Substitutes`}
              extra={substitutes.map((sub: any) => (
                <RenderPart instance={sub.part_detail} />
              ))}
            />
          ) : (
            <YesNoButton value={false} />
          );
        }
      },
      BooleanColumn({
        accessor: 'optional',
        defaultVisible: false
      }),
      BooleanColumn({
        accessor: 'consumable',
        defaultVisible: false
      }),
      BooleanColumn({
        accessor: 'allow_variants',
        defaultVisible: false
      }),
      BooleanColumn({
        accessor: 'inherited',
        defaultVisible: false
      }),
      BooleanColumn({
        accessor: 'validated',
        defaultVisible: false
      }),
      {
        accessor: 'editable_unit_price',
        title: t`Unit Price`,
        render: (_record: any, index?: number) =>
          isEditing ? (
            <NumberInput
              value={editableRecords[index ?? 0]?.editable_unit_price ?? 0}
              min={0}
              step={0.01}
              onChange={(val) => handleValueChange(index ?? 0, 'editable_unit_price', Number(val) || 0)}
              size="xs"
              w={100}
              rightSection={<Text size="xs">$</Text>}
            />
          ) : (
            <Text>
              {formatPriceRange(
                editableRecords[index ?? 0]?.editable_unit_price ?? 0,
                editableRecords[index ?? 0]?.editable_unit_price ?? 0
              )}
            </Text>
          )
      },
      {
        accessor: 'editable_total_price',
        title: t`Total Price`,
        render: (_record: any, index?: number) => (
          <Text>
            {formatPriceRange(
              editableRecords[index ?? 0]?.editable_total_price ?? 0,
              editableRecords[index ?? 0]?.editable_total_price ?? 0
            )}
          </Text>
        )
      },
      {
        accessor: 'available_stock',
        sortable: true,
        render: (record) => {
          const extra: ReactNode[] = [];

          const available_stock: number = availableStockQuantity(record);
          const on_order: number = record?.on_order ?? 0;
          const building: number = record?.building ?? 0;

          const text =
            available_stock <= 0 ? (
              <Text c='red' style={{ fontStyle: 'italic' }}>{t`No stock`}</Text>
            ) : (
              available_stock
            );

          if (record.external_stock > 0) {
            extra.push(
              <Text key='external'>
                {t`External stock`}: {record.external_stock}
              </Text>
            );
          }

          if (record.available_substitute_stock > 0) {
            extra.push(
              <Text key='substitute'>
                {t`Includes substitute stock`}:{' '}
                {record.available_substitute_stock}
              </Text>
            );
          }

          if (record.allow_variants && record.available_variant_stock > 0) {
            extra.push(
              <Text key='variant'>
                {t`Includes variant stock`}: {record.available_variant_stock}
              </Text>
            );
          }

          if (on_order > 0) {
            extra.push(
              <Text key='on_order'>
                {t`On order`}: {on_order}
              </Text>
            );
          }

          if (building > 0) {
            extra.push(
              <Text key='building'>
                {t`Building`}: {building}
              </Text>
            );
          }

          return (
            <TableHoverCard
              value={text}
              extra={extra}
              title={t`Stock Information`}
            />
          );
        }
      },
      {
        accessor: 'can_build',
        title: t`Can Build`,
        sortable: true,
        render: (record: any) => {
          if (record.can_build === null || record.can_build === undefined) {
            return '-';
          }

          if (
            !Number.isFinite(record.can_build) ||
            Number.isNaN(record.can_build)
          ) {
            return '-';
          }

          const can_build = Math.trunc(record.can_build);
          const value = (
            <Text
              fs={record.consumable && 'italic'}
              c={can_build <= 0 && !record.consumable ? 'red' : undefined}
            >
              {can_build}
            </Text>
          );

          const extra = [];

          if (record.consumable) {
            extra.push(<Text key='consumable'>{t`Consumable item`}</Text>);
          } else if (can_build <= 0) {
            extra.push(
              <Text key='no-build' c='red'>{t`No available stock`}</Text>
            );
          }

          return (
            <TableHoverCard value={value} extra={extra} title={t`Can Build`} />
          );
        }
      },
      NoteColumn({})
    ];
  }, [partId, params, isEditing, editableRecords]);

  const tableFilters: TableFilter[] = useMemo(() => {
    return [
      {
        name: 'sub_part_testable',
        label: t`Testable Part`,
        description: t`Show testable items`
      },
      {
        name: 'sub_part_trackable',
        label: t`Trackable Part`,
        description: t`Show trackable items`
      },
      {
        name: 'sub_part_assembly',
        label: t`Assembled Part`,
        description: t`Show assembled items`
      },
      {
        name: 'available_stock',
        label: t`Available Stock`,
        description: t`Show items with available stock`
      },
      {
        name: 'on_order',
        label: t`On Order`,
        description: t`Show items on order`
      },
      {
        name: 'validated',
        label: t`Validated`,
        description: t`Show validated items`
      },
      {
        name: 'inherited',
        label: t`Inherited`,
        description: t`Show inherited items`
      },
      {
        name: 'allow_variants',
        label: t`Allow Variants`,
        description: t`Show items which allow variant substitution`
      },
      {
        name: 'optional',
        label: t`Optional`,
        description: t`Show optional items`
      },
      {
        name: 'consumable',
        label: t`Consumable`,
        description: t`Show consumable items`
      },
      {
        name: 'has_pricing',
        label: t`Has Pricing`,
        description: t`Show items with pricing`
      }
    ];
  }, [partId, params]);

  const [selectedBomItem, setSelectedBomItem] = useState<any>({});

  const importSessionFields = useMemo(() => {
    const fields = dataImporterSessionFields();

    fields.model_type.hidden = true;
    fields.model_type.value = 'bomitem';

    fields.field_overrides.value = {
      part: partId
    };

    return fields;
  }, [partId]);

  const importBomItem = useCreateApiFormModal({
    url: ApiEndpoints.import_session_list,
    title: t`Import BOM Data`,
    fields: importSessionFields,
    onFormSuccess: (response: any) => {
      setSelectedSession(response.pk);
      setImportOpened(true);
    }
  });

  const newBomItem = useCreateApiFormModal({
    url: ApiEndpoints.bom_list,
    title: t`Add BOM Item`,
    fields: bomItemFields(),
    initialData: {
      part: partId
    },
    successMessage: t`BOM item created`,
    table: table
  });

  const editBomItem = useEditApiFormModal({
    url: ApiEndpoints.bom_list,
    pk: selectedBomItem.pk,
    title: t`Edit BOM Item`,
    fields: bomItemFields(),
    successMessage: t`BOM item updated`,
    table: table
  });

  const deleteBomItem = useDeleteApiFormModal({
    url: ApiEndpoints.bom_list,
    pk: selectedBomItem.pk,
    title: t`Delete BOM Item`,
    successMessage: t`BOM item deleted`,
    table: table
  });

  const editSubstitues = useEditBomSubstitutesForm({
    bomItemId: selectedBomItem.pk,
    substitutes: selectedBomItem?.substitutes ?? [],
    onClose: () => {
      table.refreshTable();
    }
  });

  const validateBom = useApiFormModal({
    url: ApiEndpoints.bom_validate,
    method: 'PUT',
    fields: {
      valid: {
        hidden: true,
        value: true
      }
    },
    title: t`Validate BOM`,
    pk: partId,
    preFormContent: (
      <Alert color='green' icon={<IconCircleCheck />} title={t`Validate BOM`}>
        <Text>{t`Do you want to validate the bill of materials for this assembly?`}</Text>
      </Alert>
    ),
    successMessage: t`BOM validated`,
    onFormSuccess: () => table.refreshTable()
  });

  const validateBomItem = useCallback((record: any) => {
    const url = apiUrl(ApiEndpoints.bom_item_validate, record.pk);

    api
      .patch(url, { valid: true })
      .then((_response) => {
        showNotification({
          title: t`Success`,
          message: t`BOM item validated`,
          color: 'green'
        });

        table.refreshTable();
      })
      .catch((_error) => {
        showNotification({
          title: t`Error`,
          message: t`Failed to validate BOM item`,
          color: 'red'
        });
      });
  }, []);

  const rowActions = useCallback(
    (record: any): RowAction[] => {
      // If this BOM item is defined for a *different* parent, then it cannot be edited
      if (record.part && record.part != partId) {
        return [
          {
            title: t`View BOM`,
            onClick: (event: any) => {
              navigateToLink(`/part/${record.part}/bom/`, navigate, event);
            },
            icon: <IconArrowRight />
          }
        ];
      }

      return [
        {
          title: t`Validate BOM Line`,
          color: 'green',
          hidden:
            partLocked ||
            record.validated ||
            !user.hasChangeRole(UserRoles.bom_upload),
          icon: <IconCircleCheck />,
          onClick: () => validateBomItem(record)
        },
        RowEditAction({
          hidden: partLocked || !user.hasChangeRole(UserRoles.bom_upload),
          onClick: () => {
            setSelectedBomItem(record);
            editBomItem.open();
          }
        }),
        {
          title: t`Edit Substitutes`,
          color: 'blue',
          hidden: partLocked || !user.hasAddRole(UserRoles.bom_upload),
          icon: <IconSwitch3 />,
          onClick: () => {
            setSelectedBomItem(record);

            
            editSubstitues.open();
          }
        },
        RowDeleteAction({
          hidden: partLocked || !user.hasDeleteRole(UserRoles.bom_upload),
          onClick: () => {
            setSelectedBomItem(record);
            deleteBomItem.open();
          }
        })
      ];
    },
    [partId, partLocked, user]
  );

  const tableActions = useMemo(() => {
    return [
      <ActionButton
        key='import-bom'
        hidden={partLocked || !user.hasAddRole(UserRoles.bom_upload)}
        tooltip={t`Import BOM Data`}
        icon={<IconFileArrowLeft />}
        onClick={() => importBomItem.open()}
      />,
      <ActionButton
        key='validate-bom'
        hidden={partLocked || !user.hasChangeRole(UserRoles.bom_upload)}
        tooltip={t`Validate BOM`}
        icon={<IconCircleCheck />}
        onClick={() => validateBom.open()}
      />,
      <AddItemButton
        key='add-bom-item'
        hidden={partLocked || !user.hasAddRole(UserRoles.bom_upload)}
        tooltip={t`Add BOM Item`}
        onClick={() => newBomItem.open()}
      />,
      <ActionButton
        key='toggle-edit'
        tooltip={isEditing ? t`Disable Edit Mode` : t`Enable Edit Mode`}
        color={isEditing ? 'red' : 'blue'}
        icon={<IconSwitch3 />}
        // onClick={() => setIsEditing(!isEditing)}
         onClick={toggleEditMode}
      />

    ];
  }, [partLocked, user, isEditing]);

  return (
    <>

      {isEditing && (
        <>
        <Group justify="space-between" mt="md">
          <Text fw={600}>{t`Total BOM Cost (USD):`}</Text>
          <Text fw={600} c="blue">
            {formatPriceRange(
              Number(totalBomCost.toFixed(4)),
              Number(totalBomCost.toFixed(4))
            )}
          </Text>
        </Group>

        <Group justify="space-between" mt="xs">
          <Text fw={600}>{t`Total Assembly Cost (INR):`}</Text>
          <Text fw={600} c="green">
            ₹{(assemblyQuantity * assemblyCost).toFixed(4)}
          </Text>
        </Group>

        <Group justify="space-between" mt="xs">
          <Text fw={600}>{t`Total BOM Cost (INR):`}</Text>
          <Text fw={600} c="orange">
            ₹{(totalBomCost * assemblyQuantity * exchangeRate).toFixed(4)}
          </Text>
        </Group>

        <Group justify="space-between" mt="xs">
          <Text fw={700}>{t`Final Total (INR):`}</Text>
          <Text fw={700} c="red">
            ₹{finalTotalINR.toFixed(4)}
          </Text>
        </Group>

        <Group mt="md" gap="md">
          <NumberInput
            label={t`Quantity`}
            value={assemblyQuantity}
            min={1}
            step={1}
            onChange={(val) => setAssemblyQuantity(Number(val) || 1)}
            w={150}
          />
          <NumberInput
            label={t`Assembly Cost (INR)`}
            value={assemblyCost}
            min={0}
            step={0.01}
            onChange={(val) => setAssemblyCost(Number(val) || 0)}
            w={180}
          />
          <NumberInput
            label={t`Additional Cost (INR)`}
            value={additionalCost}
            min={0}
            step={0.01}
            onChange={(val) => setAdditionalCost(Number(val) || 0)}
            w={180}
          />
          <NumberInput
            label={t`Exchange Rate (USD → INR)`}
            value={exchangeRate}
            min={0.01}
            step={0.01}
            onChange={(val) => setExchangeRate(Number(val) || 0)}
            w={180}
          />
        </Group>
        </>
      )}

      {importBomItem.modal}
      {newBomItem.modal}
      {editBomItem.modal}
      {validateBom.modal}
      {deleteBomItem.modal}
      {editSubstitues.modal}
      <Stack gap='xs'>
        {partLocked && (
          <Alert
            title={t`Part is Locked`}
            color='orange'
            icon={<IconLock />}
            p='xs'
          >
            <Text>{t`Bill of materials cannot be edited, as the part is locked`}</Text>
          </Alert>
        )}
        <InvenTreeTable
          url={apiUrl(ApiEndpoints.bom_list)}
          tableState={table}
          columns={tableColumns}
          props={{
            params: {
              ...params,
              part: partId,
              part_detail: true,
              sub_part_detail: true
            },
            tableActions: tableActions,
            tableFilters: tableFilters,
            modelType: ModelType.part,
            modelField: 'sub_part',
            rowActions: rowActions,
            enableSelection: !partLocked,
            enableBulkDelete: !partLocked && user.hasDeleteRole(UserRoles.bom_upload),
            enableDownload: true
          }}
        />
      </Stack>
      <ImporterDrawer
        sessionId={selectedSession ?? -1}
        opened={selectedSession != undefined && importOpened}
        onClose={() => {
          setSelectedSession(undefined);
          setImportOpened(false);
          table.refreshTable();
        }}
      />

    </>
  );
}
