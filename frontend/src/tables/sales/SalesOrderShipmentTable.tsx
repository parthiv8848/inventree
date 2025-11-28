import { t } from '@lingui/core/macro';
import { IconTruckDelivery, IconPlus  } from '@tabler/icons-react';
import { useCallback, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from '@mantine/core';


import { ApiEndpoints } from '@lib/enums/ApiEndpoints';
import { ModelType } from '@lib/enums/ModelType';
import { UserRoles } from '@lib/enums/Roles';
import { apiUrl } from '@lib/functions/Api';
import type { TableFilter } from '@lib/types/Filters';
import dayjs from 'dayjs';
import { AddItemButton } from '../../components/buttons/AddItemButton';
import { YesNoButton } from '../../components/buttons/YesNoButton';
import {
  useSalesOrderShipmentCompleteFields,
  useSalesOrderShipmentFields
} from '../../forms/SalesOrderForms';
import {
  useCreateApiFormModal,
  useDeleteApiFormModal,
  useEditApiFormModal
} from '../../hooks/UseForm';
import { useTable } from '../../hooks/UseTable';
import { useUserState } from '../../states/UserState';
import type { TableColumn } from '../Column';
import { DateColumn, LinkColumn } from '../ColumnRenderers';
import { InvenTreeTable } from '../InvenTreeTable';
import {
  type RowAction,
  RowCancelAction,
  RowEditAction,
  RowViewAction
} from '../RowActions';


export default function SalesOrderShipmentTable({
  orderId
}: Readonly<{
  orderId: number;
}>) {
  const user = useUserState();
  const navigate = useNavigate();
  const table = useTable('sales-order-shipment');


  // Define Modal for adding a new Courier Company
  const newCourierCompanyFields = useMemo(() => {
    return {
      company_name: { type: 'text', label: t`Company Name` },
      website: { type: 'url', label: t`Website (Optional)` },
      tracking_link: { type: 'url', label: t`Tracking Link (Optional)` },
    };
  }, []);


  const newCourierCompany = useCreateApiFormModal({
    url: ApiEndpoints.courier_company_list,
    fields: newCourierCompanyFields,
    title: t`Add Courier Company`,
    table: table,
  });

  const [selectedShipment, setSelectedShipment] = useState<any>({});


const newShipmentFields = useSalesOrderShipmentFields({
  modals: {
    courierCompany: newCourierCompany,
  }
});


  const editShipmentFields = useSalesOrderShipmentFields({});


  const completeShipmentFields = useSalesOrderShipmentCompleteFields({});


  const newShipment = useCreateApiFormModal({
    url: ApiEndpoints.sales_order_shipment_list,
    fields: newShipmentFields,
    title: t`Create Shipment`,
    table: table,
    initialData: {
      order: orderId
    }
  });

  const deleteShipment = useDeleteApiFormModal({
    url: ApiEndpoints.sales_order_shipment_list,
    pk: selectedShipment.pk,
    title: t`Cancel Shipment`,
    table: table
  });


  const editShipment = useEditApiFormModal({
    url: ApiEndpoints.sales_order_shipment_list,
    pk: selectedShipment.pk,
    fields: editShipmentFields,
    title: t`Edit Shipment`,
    table: table
  });


  const completeShipment = useCreateApiFormModal({
    url: ApiEndpoints.sales_order_shipment_complete,
    pk: selectedShipment.pk,
    fields: completeShipmentFields,
    title: t`Complete Shipment`,
    table: table,
    focus: 'tracking_number',
    initialData: {
      ...selectedShipment,
      shipment_date: dayjs().format('YYYY-MM-DD')
    }
  });


  const tableColumns: TableColumn[] = useMemo(() => {
    return [
      {
        accessor: 'reference',
        title: t`Shipment Reference`,
        switchable: false,
        sortable: true
      },
      {
        accessor: 'allocated_items',
        sortable: true,
        switchable: false,
        title: t`Items`
      },
      {
        accessor: 'shipped',
        title: t`Shipped`,
        switchable: true,
        sortable: false,
        render: (record: any) => <YesNoButton value={!!record.shipment_date} />
      },
      DateColumn({
        accessor: 'shipment_date',
        title: t`Shipment Date`
      }),
      {
        accessor: 'courier_company_detail',
        title: t`Courier Company`,
        sortable: false,
        switchable: true,
        render: (record: any) => {
          if (record.courier_company_detail) {
            const companyName = record.courier_company_detail.company_name || t`N/A`;
            const website = record.courier_company_detail.website || '';
            const trackingLink = record.courier_company_detail.tracking_link || '';


            let html = companyName;


            if (website) {
              html += ` (<a href="${website}" target="_blank">${website}</a>)`;
            }


            if (trackingLink) {
              html += `<br><a href="${trackingLink}" target="_blank">${t`Track here`}</a>`;
            }


            return <span dangerouslySetInnerHTML={{ __html: html }} />;
          } else {
            return '-'; // Return '-' if there's no courier company detail
          }
        }
      },
      DateColumn({
        accessor: 'delivery_date',
        title: t`Delivery Date`
      }),
      {
        accessor: 'tracking_number'
      },
      {
        accessor: 'invoice_number'
      },
      LinkColumn({
        accessor: 'link'
      }),
        {
        accessor: 'send_shipment',
        title: t`Send Shipment Mail`,
        switchable: true,
        sortable: false,
        render: (record: any) => <YesNoButton value={!!record.send_shipment} />
      },
    ];
  }, []);


  const rowActions = useCallback(
    (record: any): RowAction[] => {
      const shipped: boolean = !!record.shipment_date;


      return [
        RowViewAction({
          title: t`View Shipment`,
          modelType: ModelType.salesordershipment,
          modelId: record.pk,
          navigate: navigate
        }),
        {
          hidden: shipped || !user.hasChangeRole(UserRoles.sales_order),
          title: t`Complete Shipment`,
          color: 'green',
          icon: <IconTruckDelivery />,
          onClick: () => {
            setSelectedShipment(record);
            completeShipment.open();
          }
        },
        RowEditAction({
          hidden: !user.hasChangeRole(UserRoles.sales_order),
          tooltip: t`Edit shipment`,
          onClick: () => {
            setSelectedShipment(record);
            editShipment.open();
          }
        }),
        RowCancelAction({
          hidden: shipped || !user.hasDeleteRole(UserRoles.sales_order),
          tooltip: t`Cancel shipment`,
          onClick: () => {
            setSelectedShipment(record);
            deleteShipment.open();
          }
        })
      ];
    },
    [user]
  );


  const tableActions = useMemo(() => {
    return [
      <>
        <AddItemButton
          key='add-shipment'
          tooltip={t`Add shipment`}
          hidden={!user.hasAddRole(UserRoles.sales_order)}
          onClick={() => {
            newShipment.open();
          }}
        />
        {/* <AddItemButton
          key='add-courier-company'
          tooltip={t`Add Courier Company`}
          hidden={!user.hasAddRole(UserRoles.sales_order)}
          onClick={() => {
            newCourierCompany.open(); // Open the courier company modal
          }}
        /> */}
        {/* <Button
          key="add-courier-company"
          hidden={!user.hasAddRole(UserRoles.sales_order)}
          leftSection={<IconPlus size={16} />}   // 👈 icon on the left
          onClick={() => {
            newCourierCompany.open(); // Open the courier company modal
          }}
        >
          {t`Add Courier Company`}
        </Button> */}

      </>
    ];
  }, [user]);


  const tableFilters: TableFilter[] = useMemo(() => {
    return [
      {
        name: 'shipped',
        label: t`Shipped`,
        description: t`Show shipments which have been shipped`
      },
      {
        name: 'delivered',
        label: t`Delivered`,
        description: t`Show shipments which have been delivered`
      }
    ];
  }, []);


  return (
    <>
      {newShipment.modal}
      {editShipment.modal}
      {deleteShipment.modal}
      {completeShipment.modal}
      {newCourierCompany.modal} {/* Courier Company Modal */}
      <InvenTreeTable
        url={apiUrl(ApiEndpoints.sales_order_shipment_list)}
        tableState={table}
        columns={tableColumns}
        props={{
          tableActions: tableActions,
          tableFilters: tableFilters,
          modelType: ModelType.salesordershipment,
          enableSelection: true,
          enableReports: true,
          rowActions: rowActions,
          params: {
            order: orderId
          }
        }}
      />
    </>
  );
}