import { t } from '@lingui/core/macro';
import { useCallback, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { ApiEndpoints } from '@lib/enums/ApiEndpoints';
import { ModelType } from '@lib/enums/ModelType';
import { UserRoles } from '@lib/enums/Roles';
import { apiUrl } from '@lib/functions/Api';
import { navigateToLink } from '@lib/functions/Navigation';
import type { TableFilter } from '@lib/types/Filters';
import { AddItemButton } from '../../components/buttons/AddItemButton';
import { companyFields } from '../../forms/CompanyForms';
import {
  useCreateApiFormModal,
  useEditApiFormModal
} from '../../hooks/UseForm';
import { useTable } from '../../hooks/UseTable';
import { useUserState } from '../../states/UserState';
import {
  BooleanColumn,
  CompanyColumn,
  DescriptionColumn
} from '../ColumnRenderers';
import { InvenTreeTable } from '../InvenTreeTable';
import { type RowAction, RowEditAction } from '../RowActions';
import { Anchor } from '@mantine/core';
import { cancelEvent } from '@lib/functions/Events';
/**
 * A table which displays a list of company records,
 * based on the provided filter parameters
 */
export function CompanyTable({
  params,
  path
}: Readonly<{
  params?: any;
  path?: string;
}>) {
  const table = useTable('company');

  const navigate = useNavigate();
  const user = useUserState();

  const columns = useMemo(() => {
    return [
      {
        accessor: 'name',
        sortable: true,
        switchable: false,
        render: (record: any) => {
          return <CompanyColumn company={record} />;
        }
      },
      DescriptionColumn({}),
      BooleanColumn({
        accessor: 'active',
        title: t`Active`,
        sortable: true,
        switchable: true
      }),
      // {
      //   accessor: 'website',
      //   sortable: false
      // }
{
  accessor: 'website',
  sortable: false,
  render: (record: any) => {
    const url = record?.website;

    if (!url) {
      return '-';
    }

    return (
      <Anchor
        href={url.startsWith('http') ? url : `https://${url}`}
        target="_blank"
        rel="noopener noreferrer"
        onClick={(event: any) => {
          cancelEvent(event);
          window.open(
            url.startsWith('http') ? url : `https://${url}`,
            '_blank',
            'noopener,noreferrer'
          );
        }}
        title={url}
      >
        {url}
      </Anchor>
    );
  }
}

    ];
  }, []);

  const newCompany = useCreateApiFormModal({
    url: ApiEndpoints.company_list,
    title: t`Add Company`,
    fields: companyFields(),
    initialData: params,
    follow: true,
    modelType: ModelType.company
  });

  const [selectedCompany, setSelectedCompany] = useState<number>(0);

  const editCompany = useEditApiFormModal({
    url: ApiEndpoints.company_list,
    pk: selectedCompany,
    title: t`Edit Company`,
    fields: companyFields(),
    onFormSuccess: (record: any) => table.updateRecord(record)
  });

  const tableFilters: TableFilter[] = useMemo(() => {
    return [
      {
        name: 'active',
        label: t`Active`,
        description: t`Show active companies`
      },
      {
        name: 'is_supplier',
        label: t`Supplier`,
        description: t`Show companies which are suppliers`
      },
      {
        name: 'is_manufacturer',
        label: t`Manufacturer`,
        description: t`Show companies which are manufacturers`
      },
      {
        name: 'is_customer',
        label: t`Customer`,
        description: t`Show companies which are customers`
      }
    ];
  }, []);

  const tableActions = useMemo(() => {
    const can_add =
      user.hasAddRole(UserRoles.purchase_order) ||
      user.hasAddRole(UserRoles.sales_order) ||
      user.hasAddRole(UserRoles.manufactured);

    return [
      <AddItemButton
        key='add-company'
        tooltip={t`Add Company`}
        onClick={() => newCompany.open()}
        hidden={!can_add}
      />
    ];
  }, [user]);

  const rowActions = useCallback(
    (record: any): RowAction[] => {
      return [
        RowEditAction({
          hidden:
            !user.hasChangeRole(UserRoles.purchase_order) &&
            !user.hasChangeRole(UserRoles.sales_order),
          onClick: () => {
            setSelectedCompany(record.pk);
            editCompany.open();
          }
        })
      ];
    },
    [user]
  );

  return (
    <>
      {newCompany.modal}
      {editCompany.modal}
      <InvenTreeTable
        url={apiUrl(ApiEndpoints.company_list)}
        tableState={table}
        columns={columns}
        props={{
          params: {
            ...params
          },
          onRowClick: (record: any, index: number, event: any) => {
            if (record.pk) {
              const base = path ?? 'company';
              navigateToLink(`/${base}/${record.pk}`, navigate, event);
            }
          },
          modelType: ModelType.company,
          tableFilters: tableFilters,
          tableActions: tableActions,
          enableDownload: true,
          enableSelection: true,
          enableReports: true,
          rowActions: rowActions
        }}
      />
    </>
  );
}
