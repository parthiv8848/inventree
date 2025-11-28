import { t } from '@lingui/core/macro';
import { Group, Text, Anchor } from '@mantine/core';
import { IconShoppingCart, IconLink } from '@tabler/icons-react';
import { type ReactNode, useCallback, useMemo, useState } from 'react';

import { ApiEndpoints } from '@lib/enums/ApiEndpoints';
import { ModelType } from '@lib/enums/ModelType';
import { UserRoles } from '@lib/enums/Roles';
import { apiUrl } from '@lib/functions/Api';
import type { TableFilter } from '@lib/types/Filters';
import { AddItemButton } from '../../components/buttons/AddItemButton';
import { ActionDropdown } from '../../components/items/ActionDropdown';
import OrderPartsWizard from '../../components/wizards/OrderPartsWizard';
import { formatPriceRange } from '../../defaults/formatters';
import { usePartFields } from '../../forms/PartForms';
import { InvenTreeIcon } from '../../functions/icons';
import {
  useBulkEditApiFormModal,
  useCreateApiFormModal,
  useEditApiFormModal,
} from '../../hooks/UseForm';
import { useTable } from '../../hooks/UseTable';
import { useUserState } from '../../states/UserState';
import type { TableColumn } from '../Column';
import {
  CategoryColumn,
  DescriptionColumn,
  LinkColumn,
  PartColumn
} from '../ColumnRenderers';
import { InvenTreeTable, type InvenTreeTableProps } from '../InvenTreeTable';
import { type RowAction, RowEditAction } from '../RowActions';
import { TableHoverCard } from '../TableHoverCard';
import { cancelEvent } from '@lib/functions/Events';
import { Link } from 'react-router-dom';
import { partCategoryFields } from '../../forms/PartForms';


/**
 * Construct a list of columns for the part table
 */
function partTableColumns(): TableColumn[] {
  return [
    {
      accessor: 'name',
      title: t`Part`,
      sortable: true,
      noWrap: true,
      switchable: false,
      render: (record: any) => PartColumn({ part: record })
    },
    // {
    //   accessor: 'IPN',
    //   sortable: true
    // },
    // {
    //   accessor: 'revision',
    //   sortable: true
    // },
    {
      accessor: 'MPN',  // New column for MPN
      title: t`MPN`,
      sortable: true,
      render: (record: any) => {
        const manufacturerParts = record?.manufacturer_parts ?? [];
        if (manufacturerParts.length > 0) {
          return manufacturerParts[0]?.MPN ?? t`No MPN`;  // Get MPN from the first item
        }
        return t`No MPN`;  // Fallback text if no MPN exists
      }
    },
    // {
    //   accessor: 'units',
    //   sortable: true
    // },
    DescriptionColumn({}),
    // CategoryColumn({
    //   accessor: 'category_detail'
    // }),
      {
      accessor: 'category',
      title: t`Category`,
      sortable: true,
      render: (record: any) => {
        const category = record?.category_detail;
        if (!category) return t`No Category`;

        const url = `/part/category/${category.pk}/details`;

        return (
          <Anchor component={Link} to={url} title={category.pathstring}>
            {/* <Text size="sm" c="blue"> */}
              {category.pathstring}
            {/* </Text> */}
          </Anchor>
        );
      },
    },
    // {
    //   accessor: 'default_location',
    //   sortable: true,
    //   render: (record: any) => record.default_location_detail?.pathstring,
    //   defaultVisible: false
    // },
    {
      accessor: 'location_details',  // New column for location details
      title: t`Location Details`,
      sortable: true,
      render: (record: any) => {
        // Render the stock location details
        const locations = record?.stock_location_detail ?? [];
        if (locations.length > 0) {
          return (
            <Group gap="xs" justify="left" wrap="nowrap">
              {locations.map((location: any, index: number) => (
                <Text key={index} size="xs">{location.location.name}: {location.quantity} {record.units}</Text>
              ))}
            </Group>
          );
        }
        return t`No Location Details`;  // Default message if no location data exists
      },
      defaultVisible: true
    },
   
    {
      accessor: 'total_in_stock',
      sortable: true,

      render: (record) => {
        const extra: ReactNode[] = [];

        const stock = record?.total_in_stock ?? 0;
        const allocated =
          (record?.allocated_to_build_orders ?? 0) +
          (record?.allocated_to_sales_orders ?? 0);
        const available = Math.max(0, stock - allocated);
        const min_stock = record?.minimum_stock ?? 0;

        let text = String(stock);

        let color: string | undefined = undefined;

        if (min_stock > stock) {
          extra.push(
            <Text key='min-stock' c='orange'>
              {`${t`Minimum stock`}: ${min_stock}`}
            </Text>
          );

          color = 'orange';
        }

        if (record.ordering > 0) {
          extra.push(
            <Text key='on-order'>{`${t`On Order`}: ${record.ordering}`}</Text>
          );
        }

        if (record.building) {
          extra.push(
            <Text key='building'>{`${t`Building`}: ${record.building}`}</Text>
          );
        }

        if (record.allocated_to_build_orders > 0) {
          extra.push(
            <Text key='bo-allocations'>
              {`${t`Build Order Allocations`}: ${record.allocated_to_build_orders}`}
            </Text>
          );
        }

        if (record.allocated_to_sales_orders > 0) {
          extra.push(
            <Text key='so-allocations'>
              {`${t`Sales Order Allocations`}: ${record.allocated_to_sales_orders}`}
            </Text>
          );
        }

        if (available != stock) {
          extra.push(
            <Text key='available'>
              {t`Available`}: {available}
            </Text>
          );
        }

        if (record.external_stock > 0) {
          extra.push(
            <Text key='external'>
              {t`External stock`}: {record.external_stock}
            </Text>
          );
        }

        if (stock <= 0) {
          color = 'red';
          text = t`No stock`;
        } else if (available <= 0) {
          color = 'orange';
        } else if (available < min_stock) {
          color = 'yellow';
        }

        return (
          <TableHoverCard
            value={
              <Group gap='xs' justify='left' wrap='nowrap'>
                <Text c={color}>{text}</Text>
                {record.units && (
                  <Text size='xs' c={color}>
                    [{record.units}]
                  </Text>
                )}
              </Group>
            }
            title={t`Stock Information`}
            extra={extra}
          />
        );
      }
    },
    {
      accessor: 'price_range',
      title: t`Price Range`,
      sortable: true,
      ordering: 'pricing_max',
      defaultVisible: false,
      render: (record: any) =>
        formatPriceRange(record.pricing_min, record.pricing_max)
    },
    LinkColumn({})
  ];
}

/**
 * Construct a set of filters for the part table
 */
function partTableFilters(): TableFilter[] {
  return [
    {
      name: 'active',
      label: t`Active`,
      description: t`Filter by part active status`,
      type: 'boolean'
    },
    {
      name: 'locked',
      label: t`Locked`,
      description: t`Filter by part locked status`,
      type: 'boolean'
    },
    {
      name: 'assembly',
      label: t`Assembly`,
      description: t`Filter by assembly attribute`,
      type: 'boolean'
    },
    {
      name: 'cascade',
      label: t`Include Subcategories`,
      description: t`Include parts in subcategories`,
      type: 'boolean'
    },
    {
      name: 'component',
      label: t`Component`,
      description: t`Filter by component attribute`,
      type: 'boolean'
    },
    {
      name: 'testable',
      label: t`Testable`,
      description: t`Filter by testable attribute`,
      type: 'boolean'
    },
    {
      name: 'trackable',
      label: t`Trackable`,
      description: t`Filter by trackable attribute`,
      type: 'boolean'
    },
    {
      name: 'has_units',
      label: t`Has Units`,
      description: t`Filter by parts which have units`,
      type: 'boolean'
    },
    {
      name: 'has_ipn',
      label: t`Has IPN`,
      description: t`Filter by parts which have an internal part number`,
      type: 'boolean'
    },
    {
      name: 'has_stock',
      label: t`Has Stock`,
      description: t`Filter by parts which have stock`,
      type: 'boolean'
    },
    {
      name: 'low_stock',
      label: t`Low Stock`,
      description: t`Filter by parts which have low stock`,
      type: 'boolean'
    },
    {
      name: 'purchaseable',
      label: t`Purchaseable`,
      description: t`Filter by parts which are purchaseable`,
      type: 'boolean'
    },
    {
      name: 'salable',
      label: t`Salable`,
      description: t`Filter by parts which are salable`,
      type: 'boolean'
    },
    {
      name: 'virtual',
      label: t`Virtual`,
      description: t`Filter by parts which are virtual`,
      type: 'choice',
      choices: [
        { value: 'true', label: t`Virtual` },
        { value: 'false', label: t`Not Virtual` }
      ]
    },
    {
      name: 'is_template',
      label: t`Is Template`,
      description: t`Filter by parts which are templates`,
      type: 'boolean'
    },
    {
      name: 'is_variant',
      label: t`Is Variant`,
      description: t`Filter by parts which are variants`,
      type: 'boolean'
    },
    {
      name: 'is_revision',
      label: t`Is Revision`,
      description: t`Filter by parts which are revisions`
    },
    {
      name: 'has_revisions',
      label: t`Has Revisions`,
      description: t`Filter by parts which have revisions`
    },
    {
      name: 'has_pricing',
      label: t`Has Pricing`,
      description: t`Filter by parts which have pricing information`,
      type: 'boolean'
    },
    {
      name: 'unallocated_stock',
      label: t`Available Stock`,
      description: t`Filter by parts which have available stock`,
      type: 'boolean'
    },
    {
      name: 'starred',
      label: t`Subscribed`,
      description: t`Filter by parts to which the user is subscribed`,
      type: 'boolean'
    },
    {
      name: 'stocktake',
      label: t`Has Stocktake`,
      description: t`Filter by parts which have stocktake information`,
      type: 'boolean'
    }
  ];
}

/**
 * PartListTable - Displays a list of parts, based on the provided parameters
 * @param {Object} params - The query parameters to pass to the API
 * @returns
 */
export function PartListTable({
  props,
  defaultPartData
}: Readonly<{
  props: InvenTreeTableProps;
  defaultPartData?: any;
}>) {
  console.log("Rendering PartListTable with props:", props);
  console.log("Default part data:", defaultPartData);
  console.log("Params:", props.params);
  const tableColumns = useMemo(() => partTableColumns(), []);
  const tableFilters = useMemo(() => partTableFilters(), []);

  const table = useTable('part-list');
  const user = useUserState();

  const initialPartData = useMemo(() => {
    return defaultPartData ?? props.params ?? {};
  }, [defaultPartData, props.params]);

  const newCategoryFields = partCategoryFields({ create: true });
  var parentId;
  // console.log("parentId from params:", parentId);
  const newCategory = useCreateApiFormModal({
    url: ApiEndpoints.category_list,
    title: t`New Part Category`,
    fields: newCategoryFields,
    focus: 'name',
    initialData: {
      parent: parentId
    },
    follow: true,
    modelType: ModelType.partcategory,
    table: table
  });

  const newPart = useCreateApiFormModal({
    url: ApiEndpoints.part_list,
    title: t`Add Part`,
    fields: usePartFields({ create: true, modal:newCategory }),
    initialData: initialPartData,
    follow: true,
    modelType: ModelType.part
  });

  const [selectedPart, setSelectedPart] = useState<number>(-1);

  const editPart = useEditApiFormModal({
    url: ApiEndpoints.part_list,
    pk: selectedPart,
    title: t`Edit Part`,
    fields: usePartFields({ create: false }),
    onFormSuccess: table.refreshTable
  });

  const setCategory = useBulkEditApiFormModal({
    url: ApiEndpoints.part_list,
    items: table.selectedIds,
    title: t`Set Category`,
    fields: {
      category: {}
    },
    onFormSuccess: table.refreshTable
  });

  const orderPartsWizard = OrderPartsWizard({ parts: table.selectedRecords });

  const rowActions = useCallback(
    (record: any): RowAction[] => {
      const can_edit = user.hasChangePermission(ModelType.part);

      return [
        RowEditAction({
          hidden: !can_edit,
          onClick: () => {
            setSelectedPart(record.pk);
            editPart.open();
          }
        })
      ];
    },
    [user, editPart]
  );

  const tableActions = useMemo(() => {
    return [
      <ActionDropdown
        tooltip={t`Part Actions`}
        icon={<InvenTreeIcon icon='part' />}
        disabled={!table.hasSelectedRecords}
        actions={[
          {
            name: t`Set Category`,
            icon: <InvenTreeIcon icon='category' />,
            tooltip: t`Set category for selected parts`,
            hidden: !user.hasChangeRole(UserRoles.part),
            disabled: !table.hasSelectedRecords,
            onClick: () => {
              setCategory.open();
            }
          },
          {
            name: t`Order Parts`,
            icon: <IconShoppingCart color='blue' />,
            tooltip: t`Order selected parts`,
            hidden: !user.hasAddRole(UserRoles.purchase_order),
            onClick: () => {
              orderPartsWizard.openWizard();
            }
          }
        ]}
      />,
      <AddItemButton
        key='add-part'
        hidden={!user.hasAddRole(UserRoles.part)}
        tooltip={t`Add Part`}
        onClick={() => newPart.open()}
      />,
      // <AddItemButton
      //   key='add-part-category'
      //   tooltip={t`Add Part Category`}
      //   onClick={() => newCategory.open()}
      //   hidden={!user.hasAddRole(UserRoles.part_category)}
      // />
    ];
  }, [user, table.hasSelectedRecords]);
  // Add console.log here to inspect the 'record' data.
  const partTableColumnsWithLogging = useMemo(() => {
    const columns = partTableColumns();
    columns.forEach(column => {
      if (column.accessor === 'total_in_stock') {
        column.render = (record: any) => {
          // Log the record to inspect it
          console.log("Record for total_in_stock column:", record);

          const extra: ReactNode[] = [];
          const stock = record?.total_in_stock ?? 0;
          const allocated =
            (record?.allocated_to_build_orders ?? 0) +
            (record?.allocated_to_sales_orders ?? 0);
          const available = Math.max(0, stock - allocated);
          const min_stock = record?.minimum_stock ?? 0;

          let text = String(stock);
          let color: string | undefined = undefined;

          if (min_stock > stock) {
            extra.push(
              <Text key='min-stock' c='orange'>
                {`${t`Minimum stock`}: ${min_stock}`}
              </Text>
            );
            color = 'orange';
          }

          if (record.ordering > 0) {
            extra.push(
              <Text key='on-order'>{`${t`On Order`}: ${record.ordering}`}</Text>
            );
          }

          if (record.building) {
            extra.push(
              <Text key='building'>{`${t`Building`}: ${record.building}`}</Text>
            );
          }

          if (record.allocated_to_build_orders > 0) {
            extra.push(
              <Text key='bo-allocations'>
                {`${t`Build Order Allocations`}: ${record.allocated_to_build_orders}`}
              </Text>
            );
          }

          if (record.allocated_to_sales_orders > 0) {
            extra.push(
              <Text key='so-allocations'>
                {`${t`Sales Order Allocations`}: ${record.allocated_to_sales_orders}`}
              </Text>
            );
          }

          if (available !== stock) {
            extra.push(
              <Text key='available'>
                {t`Available`}: {available}
              </Text>
            );
          }

          if (record.external_stock > 0) {
            extra.push(
              <Text key='external'>
                {t`External stock`}: {record.external_stock}
              </Text>
            );
          }

          if (stock <= 0) {
            color = 'red';
            text = t`No stock`;
          } else if (available <= 0) {
            color = 'orange';
          } else if (available < min_stock) {
            color = 'yellow';
          }
           const url = `/part/${record.pk}/stock`;

          return (
            <Anchor component={Link} to={url}>
              <Group gap="xs" justify="left" wrap="nowrap">
                <Text c={color}>{text}</Text>
                {record.units && (
                  <Text size="xs" c={color}>
                    [{record.units}]
                  </Text>
                )}
              </Group>
            </Anchor>
            // <TableHoverCard
            //   value={
            //     <Group gap='xs' justify='left' wrap='nowrap'>
            //       <Text c={color}>{text}</Text>
            //       {record.units && (
            //         <Text size='xs' c={color}>
            //           [{record.units}]
            //         </Text>
            //       )}
            //     </Group>
            //   }
            //   title={t`Stock Information`}
            //   extra={extra}
            // />
          );
        };
      }
    });
    return columns;
  }, []);
  return (
    <>
      {newPart.modal}
      {newCategory.modal}
      {editPart.modal}
      {setCategory.modal}
      {orderPartsWizard.wizard}
      <InvenTreeTable
        url={apiUrl(ApiEndpoints.part_list)}
        tableState={table}
        columns={partTableColumnsWithLogging}
        props={{
          ...props,
          enableDownload: true,
          modelType: ModelType.part,
          tableFilters: tableFilters,
          tableActions: tableActions,
          rowActions: rowActions,
          enableSelection: true,
          enableReports: true,
          enableLabels: true,
          params: {
            ...props.params,
            category_detail: true,
            location_detail: true
          }
        }}
      />
    </>
  );
}
