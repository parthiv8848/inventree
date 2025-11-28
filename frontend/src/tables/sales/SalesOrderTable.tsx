import { t } from '@lingui/core/macro';
import { useMemo } from 'react';
import { ApiEndpoints } from '@lib/enums/ApiEndpoints';
import { ModelType } from '@lib/enums/ModelType';
import { UserRoles } from '@lib/enums/Roles';
import { apiUrl } from '@lib/functions/Api';
import type { TableFilter } from '@lib/types/Filters';
import { AddItemButton } from '../../components/buttons/AddItemButton';
import { ProgressBar } from '../../components/items/ProgressBar';
import { formatCurrency } from '../../defaults/formatters';
import { useSalesOrderFields } from '../../forms/SalesOrderForms';
import { useCreateApiFormModal } from '../../hooks/UseForm';
import { useTable } from '../../hooks/UseTable';
import { useUserState } from '../../states/UserState';
import { companyFields } from '../../forms/CompanyForms';
import {
  CompanyColumn,
  CreatedByColumn,
  CreationDateColumn,
  DescriptionColumn,
  LineItemsProgressColumn,
  ProjectCodeColumn,
  ReferenceColumn,
  ResponsibleColumn,
  ShipmentDateColumn,
  StartDateColumn,
  StatusColumn,
  TargetDateColumn,
  ShippingLabelColumn
} from '../ColumnRenderers';
import {
  AssignedToMeFilter,
  CompletedAfterFilter,
  CompletedBeforeFilter,
  CreatedAfterFilter,
  CreatedBeforeFilter,
  CreatedByFilter,
  HasProjectCodeFilter,
  MaxDateFilter,
  MinDateFilter,
  OrderStatusFilter,
  OutstandingFilter,
  OverdueFilter,
  ProjectCodeFilter,
  ResponsibleFilter,
  StartDateAfterFilter,
  StartDateBeforeFilter,
  TargetDateAfterFilter,
  TargetDateBeforeFilter
} from '../Filter';
import { InvenTreeTable } from '../InvenTreeTable';
import { Anchor } from '@mantine/core';
import { Link } from 'react-router-dom';
import type { ApiFormFieldSet } from '@lib/types/Forms';
import { Button, Progress, Stack, Text } from '@mantine/core';
import { IconFileDownload } from '@tabler/icons-react';
import { showNotification } from '@mantine/notifications'; // optional but nice
import { useState } from 'react';
import { api } from '../../../src/App';
import { ActionButton } from '../../components/buttons/ActionButton';

export function SalesOrderTable({
  partId,
  customerId
}: Readonly<{
  partId?: number;
  customerId?: number;
}>) {
  const table = useTable(!!partId ? 'salesorder-part' : 'salesorder-index');
  const user = useUserState();

  // UI state for label generation
  const [generating, setGenerating] = useState(false);
  const [progress, setProgress] = useState<number>(0);
  const [total, setTotal] = useState<number>(0);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
const [invoiceLoading, setInvoiceLoading] = useState(false);
const [dtdcLoading, setDtdcLoading] = useState(false);
const [labelsLoading, setLabelsLoading] = useState(false);

  // Helper: get selected PKs from the table state
  const getSelectedIds = (): number[] => {
    // table.selectedRecords is the pattern used by the InvenTree tableState
    return (table.selectedRecords ?? []).map((r: any) => r.pk).filter(Boolean);
  };

  // Helper: download blob as file
  const downloadBlob = (blob: Blob, filename: string) => {
    console.log("Downloading blob:", filename, blob.size);

    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  };

  // ----------------------
  // Utility: Get cookie value
  // ----------------------
  function getCookie(name: string): string | null {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) {
      const part = parts.pop();
      if (part) return part.split(';').shift() || null;
    }
    return null;
  }

  // ----------------------
  // Main handler function
  // ----------------------
const handleBatchLabelWithProgress = async () => {
  const ids = getSelectedIds();
  if (!ids.length) {
    showNotification({
      title: "No Orders Selected",
      message: "Select at least one Sales Order.",
      color: "yellow",
    });
    return;
  }

  try {
    setLabelsLoading(true);          // 🔴 disable Labels button
    setGenerating(true);             // 🔁 show progress bar block
    setStatusMessage("Starting...");
    setProgress(0);
    setTotal(0);

    const start = await api.post(
      apiUrl(ApiEndpoints.sales_order_batch_label),
      { order_ids: ids }
    );

    const taskId = start.data.task_id;
    setTaskId(taskId);
    console.log("🚀 Received taskId:", taskId);

    const interval = setInterval(async () => {
      try {
        console.log("⏳ Polling running...", taskId);
        const progressUrl = `/api/order/so/batch-shipping-label-progress/${taskId}/`;
        const res = await api.get(progressUrl);
        const data = res.data;
        console.log("Progress response:", data);

        if (data.status === "in-progress") {
          setProgress(data.progress);
          setTotal(data.total);
          setStatusMessage(`Processing ${data.progress}/${data.total}...`);
        }

        if (data.status === "ready") {
          clearInterval(interval);

          const labelUrl = data.label_download_url;
          const invoiceUrl = data.invoice_download_url;

          const labelBlob = await api.get(labelUrl, { responseType: "blob" });
          downloadBlob(labelBlob.data, `SalesOrder_Labels_${Date.now()}.pdf`);

          showNotification({
            title: "Done",
            message: "Labels downloaded.",
            color: "green",
          });

          if (invoiceUrl) {
            setStatusMessage("Downloading invoices...");
            const invoiceBlob = await api.get(invoiceUrl, { responseType: "blob" });
            downloadBlob(invoiceBlob.data, `SalesOrder_Invoices_${Date.now()}.pdf`);

            showNotification({
              title: "Done",
              message: "Invoices downloaded.",
              color: "green",
            });
          }
          // ✅ hide progress + re-enable button
          setGenerating(false);
          setLabelsLoading(false);
          setStatusMessage(null);
          setProgress(0);
          setTotal(0);
        }

        if (data.status === "failed") {
          clearInterval(interval);
          showNotification({
            title: "Failed",
            message: data.error,
            color: "red",
          });

          setGenerating(false);
          setLabelsLoading(false);
          setStatusMessage(`Failed: ${data.error ?? ""}`);
        }
      } catch (pollErr: any) {
        console.error("Polling error:", pollErr);
        clearInterval(interval);
        setGenerating(false);
        setLabelsLoading(false);
        showNotification({
          title: "Error",
          message: pollErr.message,
          color: "red",
        });
      }
    }, 800);
  } catch (err: any) {
    console.error("Start job error:", err);
    setGenerating(false);
    setLabelsLoading(false);
    showNotification({ title: "Error", message: err.message, color: "red" });
  }
};


const handleGenerateDTDC = async () => {
  setDtdcLoading(true);

  try {
    const ids = getSelectedIds();
    if (!ids.length) {
      showNotification({
        title: "No Orders Selected",
        message: "Select at least one Sales Order.",
        color: "yellow",
      });
      return;
    }

    const res = await api.post(
      apiUrl(ApiEndpoints.sales_order_generate_dtdc),
      { order_ids: ids }
    );

    if (res.data.success) {
      const shipments = res.data.created_shipments || [];
      const awbs = shipments.map((s: any) => s.awb_number);

      showNotification({
        title: "DTDC Created",
        message: `AWB: ${awbs.join(", ")}`,
        color: "green",
      });

      // TableState may not expose a typed `refresh` method; cast to any and call it if present.
      (table as any).refresh?.();

    } else {
      showNotification({
        title: "Error",
        message: res.data.error || "Unknown error",
        color: "red",
      });
    }

  } catch (err: any) {
    showNotification({
      title: "Error",
      message: err.message,
      color: "red",
    });
  } finally {
    setDtdcLoading(false);
  }
};


const handleGenerateInvoice = async () => {
  setInvoiceLoading(true);
  try {
    const ids = getSelectedIds();
    if (!ids.length) {
      showNotification({
        title: "No Orders Selected",
        message: "Select at least one Sales Order.",
        color: "yellow",
      });
      return;
    }

    const res = await api.post(
      apiUrl(ApiEndpoints.sales_order_generate_invoice),
      { order_ids: ids },
      { responseType: "blob" }
    );

    const blob = new Blob([res.data], { type: "application/pdf" });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `Invoices_${Date.now()}.pdf`;
    a.click();
    window.URL.revokeObjectURL(url);

    showNotification({
      title: "Invoice Generated",
      message: "PDF downloaded successfully.",
      color: "green",
    });
  } catch (err: any) {
    showNotification({
      title: "Error",
      message: err.message,
      color: "red",
    });
  } finally {
    setInvoiceLoading(false);
  }
};

  // Function to download the label file
  // const downloadLabel = (url: string, filename: string): void => {
  //   const link = document.createElement('a');
  //   link.href = url;
  //   link.download = filename; // Set the filename
  //   link.setAttribute('download', filename);
  //   link.style.display = 'none';

  //   // Append to body, trigger the download, and remove the link
  //   document.body.appendChild(link);
  //   link.click();

  //   // Cleanup
  //   setTimeout(() => {
  //     document.body.removeChild(link);
  //   }, 100);
  // };


  const tableFilters: TableFilter[] = useMemo(() => {
    const filters: TableFilter[] = [
      OrderStatusFilter({ model: ModelType.salesorder }),
      OutstandingFilter(),
      OverdueFilter(),
      AssignedToMeFilter(),
      MinDateFilter(),
      MaxDateFilter(),
      CreatedBeforeFilter(),
      CreatedAfterFilter(),
      TargetDateBeforeFilter(),
      TargetDateAfterFilter(),
      StartDateBeforeFilter(),
      StartDateAfterFilter(),
      {
        name: 'has_target_date',
        type: 'boolean',
        label: t`Has Target Date`,
        description: t`Show orders with a target date`
      },
      {
        name: 'has_start_date',
        type: 'boolean',
        label: t`Has Start Date`,
        description: t`Show orders with a start date`
      },
      CompletedBeforeFilter(),
      CompletedAfterFilter(),
      HasProjectCodeFilter(),
      ProjectCodeFilter(),
      ResponsibleFilter(),
      CreatedByFilter()
    ];

    if (!!partId) {
      filters.push({
        name: 'include_variants',
        type: 'boolean',
        label: t`Include Variants`,
        description: t`Include orders for part variants`
      });
    }

    // Add part_name filter for searching parts by name/SKU
    // In SalesOrderTable.tsx
      filters.push({
      name: 'part_name',
      type: 'text',
      label: t`Part Name / SKU`,
      description: t`Search sales orders by part name or SKU`
    },
    {
      name: 'include_part',
      type: 'boolean',
      label: t`Include Part`,
      description: t`Include or exclude matching parts`,
    },
    {
      name: 'fifo_stock_status',
      type: 'choice',
      label: t`Stock Based Status`,
      description: t`Filter by sales orders that are complete or pending based on stock`,
      choices: [
        { value: 'complete', label: t`Complete` },
        { value: 'pending', label: t`Pending` }
      ]
    },
    {
      name: 'region_type',
      type: 'choice',
      label: t`Country Orders`,
      description: t`Filter sales orders for customers in a specific country`,
      choices: [
        { value: 'india', label: t`India` },
        { value: 'international', label: t`International` }
      ]
    },
    {
      name: 'gujarat_orders',
      type: 'boolean',
      label: t`Gujarat Orders`,
      description: t`Filter sales orders for customers in Gujarat`
    }
    );

    return filters;
  }, [partId]);

  const params = { is_customer: true };
  // New modal for Add Company
  const newCompany = useCreateApiFormModal({
    url: ApiEndpoints.company_list,
    title: t`Add Company`,
    fields: companyFields(),
    initialData: params,
    follow: true,
    modelType: ModelType.company
  });

  const addressFields: ApiFormFieldSet = useMemo(() => {
    return {
      company: {},
      title: {},
      primary: {},
      line1: {},
      line2: {},
      postal_code: {},
      postal_city: {},
      province: {},
      country: {},
      shipping_notes: {},
      internal_shipping_notes: {},
      link: {}
    };
  }, []);

  const newAddress = useCreateApiFormModal({
    url: ApiEndpoints.address_list,
    title: t`Add Address`,
    fields: addressFields,
    // initialData: {
    //   company: companyId
    // },
    successMessage: t`Address created`,
    table: table
  });

  // Pass the newCompany modal to the salesOrderFields
  const salesOrderFields = useSalesOrderFields({
    modals: {
      company: newCompany,
      address: newAddress
    }

  });

  const newSalesOrder = useCreateApiFormModal({
    url: ApiEndpoints.sales_order_list,
    title: t`Add Sales Order`,
    fields: salesOrderFields,
    initialData: {
      customer: customerId
    },
    follow: true,
    modelType: ModelType.salesorder
  });

const tableActions = useMemo(() => [
  <AddItemButton
    key="add"
    tooltip="Add Sales Order"
    onClick={() => newSalesOrder.open()}
    hidden={!user.hasAddRole(UserRoles.sales_order)}
  />,

  <ActionButton
    key="invoice"
    tooltip="Generate Invoice"
    icon={<IconFileDownload size={16} />}
    color="grape"
    disabled={!table.selectedRecords?.length}
    loading={invoiceLoading}                    // 🔥 here
    onClick={handleGenerateInvoice}
  />,

  <ActionButton
    key="dtdc"
    tooltip="Generate DTDC"
    icon={<IconFileDownload size={16} />}
    color="blue"
    disabled={!table.selectedRecords?.length}
    loading={dtdcLoading}                       // 🔥 here
    onClick={handleGenerateDTDC}
  />,

  <ActionButton
    key="labels"
    tooltip="Generate Labels"
    icon={<IconFileDownload size={16} />}
    variant="default"
    disabled={!table.selectedRecords?.length}
    loading={labelsLoading}                     // 🔥 here
    onClick={handleBatchLabelWithProgress}
  />,
], [
  table.selectedRecords,
  invoiceLoading,
  dtdcLoading,
  labelsLoading,
  user,
  newSalesOrder,
]);


  const tableColumns = useMemo(() => {
    return [
      ReferenceColumn({}),
      // {
      //   accessor: 'customer__name',
      //   title: t`Customer`,
      //   sortable: true,
      //   render: (record: any) => <CompanyColumn company={record.customer_detail} />
      // },
      {
        accessor: 'customer__name',
        title: t`Customer`,
        sortable: true,
        render: (record: any) => {
          const customer = record?.customer_detail;
          if (!customer) return '-';

          const url = `/company/${customer.pk}/details`;

          return (
            <Anchor component={Link} to={url} title={customer.name}>
              <CompanyColumn company={customer} />
            </Anchor>
          );
        }
      },
      // Use the ShippingLabelColumn here
      ShippingLabelColumn({}),  // This is where you add the custom column for shipping labels

      {
        accessor: 'customer_reference',
        title: t`Customer Reference`
      },
      DescriptionColumn({}),
      LineItemsProgressColumn(),
      {
        accessor: 'shipments_count',
        title: t`Shipments`,
        render: (record: any) => (
          <ProgressBar progressLabel value={record.completed_shipments_count} maximum={record.shipments_count} />
        )
      },
      StatusColumn({ model: ModelType.salesorder }),
      ProjectCodeColumn({ defaultVisible: false }),
      CreationDateColumn({ defaultVisible: false }),
      CreatedByColumn({ defaultVisible: false }),
      StartDateColumn({ defaultVisible: false }),
      TargetDateColumn({}),
      ShipmentDateColumn({}),
      ResponsibleColumn({}),
      {
        accessor: 'total_price',
        title: t`Total Price`,
        sortable: true,
        render: (record: any) => formatCurrency(record.total_price, { currency: record.order_currency || record.customer_detail?.currency })
      }
    ];
  }, []);

  return (
    <>
      {newSalesOrder.modal}
      {newCompany.modal} {/* Keep this modal rendering here */}
      {newAddress.modal}

      {/* {generating && (
        <Stack gap="xs" mb="sm">
          <Text size="sm">{statusMessage}</Text>
          <Progress value={total ? (progress / total) * 100 : 0} w={300} />
          <Text size="xs">Progress: {progress}/{total}</Text>
        </Stack>
      )} */}

      {generating && (
        <div
          style={{
            position: "fixed",
            bottom: "20px",
            right: "20px",
            zIndex: 9999,
            width: "260px",
            background: "white",
            padding: "12px",
            borderRadius: "8px",
            boxShadow: "0 2px 12px rgba(0,0,0,0.15)"
          }}
        >
          <Stack gap={6}>
            <Text size="sm">{statusMessage}</Text>

            <ProgressBar
              value={progress}
              maximum={total || 1}
              progressLabel
              animated
              size="sm"
            />
          </Stack>
        </div>
      )}

      <InvenTreeTable
        url={apiUrl(ApiEndpoints.sales_order_list)}
        tableState={table}
        columns={tableColumns}
        props={{
          params: {
            customer_detail: true,
            part: partId,
            customer: customerId
          },
          tableFilters: tableFilters,
          tableActions: tableActions,
          modelType: ModelType.salesorder,
          enableSelection: true,
          enableDownload: true,
          enableReports: true
        }}
      />
    </>
  );
}