import { t, Trans } from '@lingui/macro';
import { useMemo, useState, useCallback, useEffect, useRef } from 'react';
import {
  Button,
  Group,
  Paper,
  Stack,
  Text,
  Divider,
  Modal,
  Alert,
  Space
} from '@mantine/core';
import {
  IconBarcode,
  IconReload,
  IconPackage,
  IconCircleCheck,
  IconAlertCircle
} from '@tabler/icons-react';
import dayjs from 'dayjs';

import { InvenTreeTable } from '../../tables/InvenTreeTable';
import { useTable } from '../../hooks/UseTable';
import { apiUrl } from '@lib/functions/Api';
import { showNotification } from '@mantine/notifications';
import { api } from '../../App';
import { ModelType } from '@lib/enums/ModelType';
import type { TableFilter } from '@lib/types/Filters';
import { BarcodeInput } from '../../components/barcodes/BarcodeInput';
import PageTitle from '../../components/nav/PageTitle';
import { StylishText } from '../../components/items/StylishText';

export default function SalesOrderScanner() {
  const table = useTable('salesorder-scan-history');
  const SCAN_HISTORY_URL = apiUrl('/api/order/so/scan-history/');

  const [refreshKey, setRefreshKey] = useState(0);
  const [barcodeModalOpened, setBarcodeModalOpened] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [stats, setStats] = useState({ total: 0, success: 0, failed: 0 });
  const [scanMessage, setScanMessage] = useState<{ type: 'success' | 'warning' | 'error', message: string } | null>(null);

  // ============================
  // 🔊 Audio Refs (for feedback sounds)
  // ============================
  const successSound = useRef<HTMLAudioElement | null>(null);
  const warningSound = useRef<HTMLAudioElement | null>(null);
  const errorSound = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    successSound.current = new Audio('/sounds/success.mp3');
    warningSound.current = new Audio('/sounds/warning.mp3');
    errorSound.current = new Audio('/sounds/error.mp3');
  }, []);

  const playSound = (type: 'success' | 'warning' | 'error') => {
    try {
      if (type === 'success') successSound.current?.play();
      else if (type === 'warning') warningSound.current?.play();
      else errorSound.current?.play();
    } catch (err) {
      console.warn('[Sound] Playback failed:', err);
    }
  };

  // ============================
  // 🔍 Filters
  // ============================
  const tableFilters: TableFilter[] = useMemo(() => {
    return [
      {
        name: 'search',
        type: 'text',
        label: t`Search`,
        description: t`Search by Barcode or Order Reference`
      },
      {
        name: 'status',
        type: 'choice',
        label: t`Status`,
        description: t`Filter by scan status`,
        choices: [
          { value: '', label: t`All` },
          { value: 'success', label: t`Success` },
          { value: 'error', label: t`Error` },
          { value: 'partial_error', label: t`Partial Error` }
        ]
      },
      {
        name: 'created_after',
        type: 'date',
        label: t`Created After`,
        description: t`Show scans created after this date`
      },
      {
        name: 'created_before',
        type: 'date',
        label: t`Created Before`,
        description: t`Show scans created before this date`
      }
    ];
  }, []);

  // ============================
  // 🧾 Barcode Scan + Ship
  // ============================
  const scanAndShip = useCallback(async (barcode: string) => {
    console.log(`[DEBUG] Scanning barcode: ${barcode}`);
    setIsProcessing(true);

    try {
      const response = await api.post(`/api/order/so/scan-ship/${barcode}/`);
      const res = response.data;
      console.log('[DEBUG] Scan Response:', res);

      if (res.status === 'success') {
        playSound('success');
        setScanMessage({ type: 'success', message: res.message || 'Order shipped successfully' });
      } else if (res.status === 'partial_error') {
        playSound('warning');
        setScanMessage({ type: 'warning', message: res.message || 'Some items failed to ship' });
      } else {
        playSound('error');
        setScanMessage({ type: 'error', message: res.message || 'Failed to ship order' });
      }

      setRefreshKey((prev) => prev + 1);

    } catch (err: any) {
      playSound('error');
      console.error('[ERROR] Scan failed:', err);
      setScanMessage({ type: 'error', message: err?.response?.data?.message || 'Error while processing scan' });
    } finally {
      setIsProcessing(false);
      // Do NOT close the modal here
    }
  }, []);

  // ============================
  // 📊 Fetch stats from backend
  // ============================
  useEffect(() => {
    (async () => {
      try {
        const res = await api.get(SCAN_HISTORY_URL);
        const data = res.data || [];
        const total = data.length;
        const success = data.filter((d: any) => d.status === 'success').length;
        const failed = data.filter((d: any) => d.status !== 'success').length;
        setStats({ total, success, failed });
      } catch (e) {
        console.warn('⚠️ Failed to load stats', e);
      }
    })();
  }, [refreshKey]);

  // ============================
  // 🧱 Table Columns
  // ============================
  const tableColumns = useMemo(() => {
    return [
      { accessor: 'barcode', title: t`Barcode`, sortable: true },
      { accessor: 'order_reference', title: t`Order Number`, sortable: true },
      {
        accessor: 'status',
        title: t`Status`,
        sortable: true,
        render: (record: any) => {
          if (record.status === 'success')
            return <Text c="green">✅ <Trans>Shipped</Trans></Text>;
          if (record.status === 'error' || record.status === 'partial_error')
            return <Text c="red">❌ <Trans>Error</Trans></Text>;
          return <Text c="dimmed">⏳ <Trans>Processing</Trans></Text>;
        }
      },
      {
        accessor: 'message',
        title: t`Message`,
        render: (record: any) => (
          <Text size="sm" c="dimmed">{record.message || '-'}</Text>
        )
      },
      {
        accessor: 'created_at',
        title: t`Timestamp`,
        sortable: true,
        render: (record: any) =>
          dayjs(record.created_at).format('YYYY-MM-DD HH:mm:ss')
      }
    ];
  }, []);

  // ============================
  // ⚙️ Table Actions
  // ============================
  const tableActions = useMemo(() => {
    return [
      <Button
        key="scan-barcode"
        leftSection={<IconBarcode size={16} />}
        onClick={() => setBarcodeModalOpened(true)}
      >
        <Trans>Scan Barcode</Trans>
      </Button>,
      <Button
        key="refresh"
        variant="light"
        color="gray"
        leftSection={<IconReload size={16} />}
        onClick={() => setRefreshKey((prev) => prev + 1)}
      >
        <Trans>Refresh</Trans>
      </Button>
    ];
  }, []);

  // ============================
  // 🧾 Return Page Layout
  // ============================
  return (
    <>
      <PageTitle title={t`Sales Order Shipping Scanner`} />

      {/* 🔊 Sound Elements */}
      <audio src="/sounds/success.mp3" preload="auto" />
      <audio src="/sounds/warning.mp3" preload="auto" />
      <audio src="/sounds/error.mp3" preload="auto" />

      {/* Barcode Modal */}
      <Modal
        opened={barcodeModalOpened}
        onClose={() => setBarcodeModalOpened(false)}
        title={t`Scan Sales Order`}
        centered
      >
        <Stack>
          {scanMessage && (
              <Alert color={
                scanMessage.type === 'success' ? 'green' :
                scanMessage.type === 'warning' ? 'orange' :
                'red'
              } icon={
                scanMessage.type === 'success' ? <IconCircleCheck /> : <IconAlertCircle />
              }>
                {scanMessage.message}
              </Alert>
            )}

          <Divider />
          <BarcodeInput onScan={(barcode) => scanAndShip(barcode)} />
          {isProcessing && (
            <Alert color="blue" icon={<IconPackage />}>
              <Trans>Processing scan...</Trans>
            </Alert>
          )}
        </Stack>
      </Modal>

      <InvenTreeTable
        key={refreshKey}
        url={SCAN_HISTORY_URL}
        tableState={table}
        columns={tableColumns}
        props={{
          modelType: ModelType.salesorder,
          tableFilters: tableFilters,
          tableActions: tableActions,
          enableSelection: true,
          enableDownload: true,
          enableFilters: true
        }}
      />

      <Space h="md" />

      <Paper p="sm" shadow="xs">
        <Stack gap="xs">
          <StylishText size="lg">{t`Statistics`}</StylishText>
          <Divider />
          <Group justify="space-between">
            <Text c="dimmed">{t`Total Scanned`}</Text>
            <Text fw={600}>{stats.total}</Text>
          </Group>
          <Group justify="space-between">
            <Text c="green">{t`Successful`}</Text>
            <Text fw={600} c="green">{stats.success}</Text>
          </Group>
          <Group justify="space-between">
            <Text c="red">{t`Failed`}</Text>
            <Text fw={600} c="red">{stats.failed}</Text>
          </Group>
        </Stack>
      </Paper>
    </>
  );
}
