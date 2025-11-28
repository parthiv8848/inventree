import { t } from '@lingui/core/macro';
import {
  Box,
  Button,
  FileInput,
  Group,
  Text,
  Textarea,
  Checkbox,
  Stack,
  Title,
  Anchor,
  Alert
} from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { useMemo, useState, useEffect, useCallback } from 'react';
import { IconUpload, IconDownload } from '@tabler/icons-react';

import { ApiEndpoints } from '@lib/enums/ApiEndpoints';
import { apiUrl } from '@lib/functions/Api';
import { useTable } from '../../hooks/UseTable';
import type { TableColumn } from '../Column';
import { InvenTreeTable } from '../InvenTreeTable';

interface ChecklistItem {
  id: number;
  item: string;
  status: number;
  comments: string;
  category: 'SCHLIB' | 'PCBLIB';
  file?: string;
  uploaded_by?: string;
  last_updated_by?: string;
}

interface ComponentChecklistTableProps {
  partId: number;
}

export default function ComponentChecklistTable({
  partId
}: Readonly<ComponentChecklistTableProps>) {
  const [checklistData, setChecklistData] = useState<ChecklistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [schlibFile, setSchlibFile] = useState<File | null>(null);
  const [pcblibFile, setPcblibFile] = useState<File | null>(null);

  const schlibTable = useTable('schlib-checklist');
  const pcblibTable = useTable('pcblib-checklist');

  // Fetch checklist data for the specific partId
  const fetchChecklistData = useCallback(async () => {
    if (!partId) {
      console.warn("❌ Part ID not provided to ComponentChecklistTable");
      return;
    }

    const apiEndpoint = apiUrl(ApiEndpoints.component_checklist, partId); // Using apiUrl
    console.log("🌍 Fetching checklist from:", apiEndpoint);

    try {
      const response = await fetch(apiEndpoint);
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data: ChecklistItem[] = await response.json();

      // Ensure data is always an array
      if (Array.isArray(data)) {
        setChecklistData(data);
      } else {
        console.error("The fetched data is not an array:", data);
        setChecklistData([]);  // Set to an empty array in case of invalid data
      }

    } catch (error) {
      console.error("Failed to load checklist data:", error);
      notifications.show({
        title: t`Error`,
        message: t`Failed to load component checklist`,
        color: 'red',
      });
    } finally {
      setLoading(false);
    }
  }, [partId]);

  useEffect(() => {
    fetchChecklistData();
  }, [fetchChecklistData]);

  // Filter items by category
  const schlibItems = useMemo(() =>
    checklistData.filter(item => item.category === 'SCHLIB'),
    [checklistData]
  );
  console.log("Filtered SCHLIB items:", schlibItems);
  const pcblibItems = useMemo(() =>
    checklistData.filter(item => item.category === 'PCBLIB'),
    [checklistData]
  );

  // Update checklist item
  const updateChecklistItem = async (
    itemId: number,
    updates: Partial<ChecklistItem>
  ) => {
    try {
      // Log the request being made
      console.log(`Updating checklist item ${itemId}:`);
      console.log(`Request body:`, { ...updates, part: partId });

      const apiEndpoint = apiUrl(ApiEndpoints.component_checklist_item, itemId); // Using apiUrl with itemId
      const response = await fetch(apiEndpoint, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCSRFToken(),
        },
        body: JSON.stringify({
          ...updates,
          part: partId,
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const updatedItem = await response.json();

      // Log the response received
      console.log(`Response received for checklist item ${itemId}:`, updatedItem);

      // Update local state
      setChecklistData(prev =>
        prev.map(item =>
          item.id === itemId
            ? { ...item, ...updates, last_updated_by: updatedItem.last_updated_by }
            : item
        )
      );

      // Log the updated state of the item
      console.log(`Updated item ${itemId}:`, updatedItem);

      notifications.show({
        title: t`Success`,
        message: t`Checklist item updated successfully`,
        color: 'green',
      });

    } catch (error) {
      // Log any errors
      console.error("Update error:", error);
      notifications.show({
        title: t`Error`,
        message: t`Error updating checklist item`,
        color: 'red',
      });
      throw error;
    }
  };


  // Handle status change
  // Handle status change
  const handleStatusChange = (item: ChecklistItem, checked: boolean) => {
    modals.openConfirmModal({
      title: t`Confirm Status Change`,
      children: (
        <Text size="sm">
          {t`Are you sure you want to change the checklist status?`}
        </Text>
      ),
      labels: { confirm: t`Confirm`, cancel: t`Cancel` },
      onConfirm: () => {
        // Log before updating
        console.log(`Updating status for item ${item.id}:`);
        console.log(`Current status: ${item.status === 1 ? 'Completed' : 'Not Completed'}`);
        console.log(`New status: ${checked ? 'Completed' : 'Not Completed'}`);

        updateChecklistItem(item.id, { status: checked ? 1 : 0 });

        // Log after the update
        console.log(`Status updated successfully for item ${item.id}.`);
        console.log(`Updated status: ${checked ? 'Completed' : 'Not Completed'}`);
      },
    });
  };


  // Handle comment change
  const handleCommentChange = (item: ChecklistItem, comments: string) => {
    updateChecklistItem(item.id, { comments });
  };

  // Handle file upload
  const handleUpload = async (
    category: 'SCHLIB' | 'PCBLIB',
    file: File | null
  ) => {
    if (!file) {
      notifications.show({
        title: t`Warning`,
        message: t`Please select a file to upload.`,
        color: 'yellow',
      });
      return;
    }

    // Check if all items are completed
    const categoryItems = category === 'SCHLIB' ? schlibItems : pcblibItems;
    const allComplete = categoryItems.every(item => item.status === 1);

    if (!allComplete) {
      notifications.show({
        title: t`Warning`,
        message: t`All checklist items for ${category} must be completed before upload.`,
        color: 'yellow',
      });
      return;
    }

    const formData = new FormData();
    formData.append('file', file);
    formData.append('category', category);
    formData.append('part', partId.toString());

    try {
      const apiEndpoint = apiUrl(ApiEndpoints.component_checklist_upload); // Using apiUrl for the upload endpoint
      const response = await fetch(apiEndpoint, {
        method: 'POST',
        headers: {
          'X-CSRFToken': getCSRFToken(),
        },
        body: formData,
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      notifications.show({
        title: t`Success`,
        message: t`File uploaded successfully for ${category}`,
        color: 'green',
      });

      // Refresh data after upload
      await fetchChecklistData();

      // Clear file input
      if (category === 'SCHLIB') {
        setSchlibFile(null);
      } else {
        setPcblibFile(null);
      }

    } catch (error) {
      console.error("Upload error:", error);
      notifications.show({
        title: t`Error`,
        message: t`Error uploading file.`,
        color: 'red',
      });
    }
  };

  // Table columns
  const getTableColumns = (category: 'SCHLIB' | 'PCBLIB'): TableColumn[] => [
    {
      accessor: 'item',
      title: t`Checklist Item`,
      sortable: false,
    },
    {
      accessor: 'status',
      title: t`Status`,
      sortable: false,
      render: (record: ChecklistItem) => (
        <Checkbox
          checked={record.status === 1}
          onChange={(event) => handleStatusChange(record, event.currentTarget.checked)}
        />
      ),
    },
{
  accessor: 'comments',
  title: t`Comments`,
  sortable: false,
  render: (record: ChecklistItem) => {
    const [localComment, setLocalComment] = useState(record.comments || '');
    const [saving, setSaving] = useState(false);

    const saveComment = async () => {
      if (localComment === record.comments) return; // no changes
      setSaving(true);
      try {
        await handleCommentChange(record, localComment); // API call
        record.comments = localComment; // update table state
      } catch (error) {
        console.error('Failed to save comment', error);
        setLocalComment(record.comments || ''); // revert on error
      } finally {
        setSaving(false);
      }
    };

    return (
      <Textarea
        value={localComment}
        onChange={(event) => setLocalComment(event.currentTarget.value)}
        onBlur={() => saveComment()} // ✅ auto-save on blur
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault(); // prevent newline
            saveComment();
          }
        }}
        rows={1}
        autosize
      />
    );
  },
},
    {
      accessor: 'last_updated_by',
      title: t`Last Updated By`,
      sortable: false,
      render: (record: ChecklistItem) => (
        <Text size="sm" c="dimmed">
          {record.last_updated_by || t`Unknown`}
        </Text>
      ),
    },
  ];

  // Render upload section
  const renderUploadSection = (category: 'SCHLIB' | 'PCBLIB') => {
    const items = category === 'SCHLIB' ? schlibItems : pcblibItems;
    const file = category === 'SCHLIB' ? schlibFile : pcblibFile;
    const setFile = category === 'SCHLIB' ? setSchlibFile : setPcblibFile;

    const itemWithFile = items.find(item => item.file);
    const existingFile = itemWithFile?.file;
    const uploader = itemWithFile?.uploaded_by;

    return (
      <Box mb="md">
        <Group>
          <FileInput
            placeholder={t`Select ${category} file`}
            value={file}
            onChange={setFile}
            accept=".schlib,.pcblib"
          />
          <Button
            leftSection={<IconUpload size={16} />}
            onClick={() => handleUpload(category, file)}
          >
            {t`Upload ${category}`}
          </Button>
        </Group>

        {existingFile && (
          <Group mt="sm">
            <Anchor
              href={existingFile}
              target="_blank"
              download
            >
              <Button
                variant="outline"
                size="sm"
                leftSection={<IconDownload size={16} />}
              >
                {t`Download ${category} File`}
              </Button>
            </Anchor>
            {uploader && (
              <Text size="sm" c="dimmed">
                ({t`Uploaded by`}: {uploader})
              </Text>
            )}
          </Group>
        )}
      </Box>
    );
  };

  if (loading) {
    return <Text>{t`Loading checklist...`}</Text>;
  }

  return (
    <Stack>
      {/* SCHLIB Section */}
      <Box>
        <Title order={5} mb="md">{t`Schematic Symbol Verification Checklist`}</Title>

        <InvenTreeTable
          tableState={schlibTable}
          columns={getTableColumns('SCHLIB')}
          tableData={schlibItems}
          props={{}}
        />

        {renderUploadSection('SCHLIB')}
      </Box>

      {/* PCBLIB Section */}
      <Box>
        <Title order={5} mb="md">{t`Footprint Verification Checklist`}</Title>
        <InvenTreeTable
          tableState={pcblibTable}
          columns={getTableColumns('PCBLIB')}
          tableData={pcblibItems}
          props={{}}
        />

        {renderUploadSection('PCBLIB')}
      </Box>
    </Stack>
  );
}

// Helper function to get CSRF token
function getCSRFToken(): string {
  const csrfToken = document.cookie
    .split('; ')
    .find(row => row.startsWith('csrftoken='))
    ?.split('=')[1];
  return csrfToken || '';
}

const csrfToken = getCSRFToken();
console.log("CSRF Token:", csrfToken);