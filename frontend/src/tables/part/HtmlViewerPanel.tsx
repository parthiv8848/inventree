import { useState, useMemo, useCallback } from 'react';
import { Group, Text, Button, FileInput, TextInput, Stack, Modal } from '@mantine/core';
import { t } from '@lingui/core/macro';
import { useTable } from '../../hooks/UseTable';
import { useCreateApiFormModal, useDeleteApiFormModal, useEditApiFormModal } from '../../hooks/UseForm';
import { InvenTreeTable } from '../InvenTreeTable';
import { RowEditAction, RowDeleteAction, type RowAction } from '../RowActions';
import { useUserState } from '../../states/UserState';
import { UserRoles } from '@lib/enums/Roles';
import { apiUrl } from '@lib/functions/Api';
import { ApiEndpoints } from '@lib/enums/ApiEndpoints';

// Utility to get cookie (for CSRF)
function getCSRFToken(): string {
  const csrfToken = document.cookie
    .split('; ')
    .find(row => row.startsWith('csrftoken='))
    ?.split('=')[1];
  return csrfToken || '';
}

export default function PartHtmlFileTable({ partId }: { partId: number }) {
  const table = useTable('part-html-files');
  const user = useUserState();

  // Set the idAccessor to 'id' since your API returns 'id' instead of 'pk'
  table.idAccessor = 'id';

  // State for the upload modal
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState('');

  // Initialize selectedFileId as null instead of undefined
  const [selectedFileId, setSelectedFileId] = useState<number | null>(null);

  const htmlFileFields = useMemo(() => ({
    name: {},
    file: {
      field_type: 'file upload' as const,   // 👈 cast as const
    },
    part: {
      hidden: true,
    },
  }), []);

  // Separate modals for each operation
  const newHtmlFile = useCreateApiFormModal({
    url: ApiEndpoints.html_file_list,
    title: t`Upload HTML File`,
    fields: htmlFileFields,
    initialData: { part: partId },
    table: table,
    onFormSuccess: () => table.refreshTable(),  // ✅ correct callback
  });

  const editHtmlFile = useEditApiFormModal({
    url: ApiEndpoints.html_file_list,
    pk: selectedFileId ?? undefined,
    title: t`Edit HTML File`,
    fields: {
      name: {},
      file: {
        field_type: 'file upload' as const,   // 👈 cast as const
      },
    },
    table: table,
  });

  const deleteHtmlFile = useDeleteApiFormModal({
    url: ApiEndpoints.html_file_list,
    pk: selectedFileId ?? undefined,
    title: t`Delete HTML File`,
    table: table,
  });

  const tableColumns = useMemo(() => [
    {
      accessor: 'name',
      title: t`File Name`,
      render: (record: any) => (
        <Text c="blue" style={{ cursor: 'pointer' }} onClick={() => viewHtml(record.file)}>
          {record.name}
        </Text>
      ),
    },
    {
      accessor: 'preview',
      title: t`Preview`,
      render: (record: any) => (
        <Button size="xs" onClick={() => viewHtml(record.file)}>
          {t`View`}
        </Button>
      ),
    },
  ], []);

  const rowActions = useCallback(
    (record: any): RowAction[] => {
      // Use record.id instead of record.pk since your API returns 'id'
      const recordId = record.pk || record.id;

      return [
        RowEditAction({
          // 👈 CHANGED: Use dedicated HTML file role instead of part role
          hidden: !user.hasChangeRole(UserRoles.part_html_file),
          onClick: () => {
            console.log('Edit clicked for record:', recordId);
            setSelectedFileId(recordId);
            setTimeout(() => {
              editHtmlFile.open();
            }, 10);
          },
        }),
        RowDeleteAction({
          // 👈 CHANGED: Use dedicated HTML file role instead of part role
          hidden: !user.hasDeleteRole(UserRoles.part_html_file),
          onClick: () => {
            console.log('Delete clicked for record:', recordId);
            setSelectedFileId(recordId);
            setTimeout(() => {
              deleteHtmlFile.open();
            }, 10);
          },
        }),
      ];
    },
    [user, editHtmlFile, deleteHtmlFile]
  );

  const csrftoken = getCSRFToken();
  console.log('CSRF Token:', csrftoken); // Debugging line

  function viewHtml(fileUrl: string) {
    const fullUrl = fileUrl.startsWith('http')
      ? fileUrl
      : `${window.location.origin}${fileUrl}`;
    window.open(fullUrl, '_blank');
  }

  // Enhanced upload function with better error handling
  const handleUpload = async () => {
    if (!file || !name) return;

    try {
      const formData = new FormData();
      formData.append('name', name);
      formData.append('file', file);
      formData.append('part', String(partId));

      const csrftoken = getCSRFToken();
      console.log('CSRF Token:', csrftoken); // Debugging line

      const response = await fetch(apiUrl(ApiEndpoints.html_file_list), {
        method: 'POST',
        body: formData,
        credentials: 'include',
        headers: {
          'X-CSRFToken': csrftoken || '',
        },
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: 'Upload failed' }));
        throw new Error(errorData.detail || `HTTP ${response.status}: ${response.statusText}`);
      }

      // Success
      setFile(null);
      setName('');
      setUploadModalOpen(false);
      table.refreshTable(); // Use the proper table refresh method

    } catch (error: any) {
      console.error('Upload error:', error);
      alert(`Upload failed: ${error.message}`);
    }
  };

  return (
    <>
      {/* All modals */}
      {newHtmlFile.modal}
      {editHtmlFile.modal}
      {deleteHtmlFile.modal}

      <Group justify="flex-start" mb="md">
        {/* 👈 CHANGED: Check for add permission on HTML file role */}
        <Button 
          size="xs" 
          onClick={() => newHtmlFile.open()}
          style={{ 
            display: user.hasAddRole(UserRoles.part_html_file) ? 'block' : 'none' 
          }}
        >
          {t`Add New HTML File`}
        </Button>
      </Group>

      <InvenTreeTable
        url={apiUrl(ApiEndpoints.html_file_list)}
        tableState={table}
        columns={tableColumns}
        props={{
          params: { part: partId },
          rowActions: rowActions,
          enableRefresh: true, // Ensure refresh is enabled
        }}
      />
    </>
  );
}