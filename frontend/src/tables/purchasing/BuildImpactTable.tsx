import { t } from '@lingui/core/macro';
import {
  Alert,
  Button,
  Checkbox,
  Collapse,
  Group,
  NumberInput,
  Paper,
  Select,
  Stack,
  Table,
  Text,
  Title,
  ActionIcon,
  Box
} from '@mantine/core';
import { IconAlertCircle, IconActivity, IconChevronDown, IconChevronRight } from '@tabler/icons-react';
import React, { type ReactNode, useMemo, useState, useEffect } from 'react';

import { ApiEndpoints } from '@lib/enums/ApiEndpoints';
import { ModelType } from '@lib/enums/ModelType';
import { UserRoles } from '@lib/enums/Roles';
import { apiUrl } from '@lib/functions/Api';
import { useTable } from '../../hooks/UseTable';
import { useUserState } from '../../states/UserState';
import type { TableColumn } from '../Column';
import { InvenTreeTable } from '../InvenTreeTable';
// Update the import path below to the correct location of your api instance:
import { api } from '../../App'; // adjust the path as needed

interface BuildData {
  build_id: number;
  build: string;
  can_fulfill: boolean;
  max_build_possible: number;
  parts: PartData[];
}

interface PartData {
  part?: {
    id: number;
    name: string;
    description?: string;
  };
  required: number;
  available_stock: number;
  available_stock_total: number;
  incoming_stock: number;
  incoming_stock_total: number;
  virtual_stock: number;
  shortfall: number;
  can_fulfill: boolean;
  // Optional list of purchase order references associated with this part
  po_list?: {
    id?: number;
    reference: string;
    received_date?: string;  // ⭐ new
    quantity?: number;
  }[];
  
}

interface PendingPO {
  id: number;
  reference: string;
  supplier__name: string;
  target_date: string;
}

interface BuildImpactData {
  results: BuildData[];
  pending_pos: PendingPO[];
}

/*
 * Construct a table listing build impact analysis
 */
export function BuildImpactTable(): ReactNode {
  const table = useTable('buildimpact');
  const user = useUserState();
  
  // State for build impact data
  const [buildData, setBuildData] = useState<BuildData[]>([]);
  const [pendingPos, setPendingPos] = useState<PendingPO[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  // State for expanded rows
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set());
  
  // State for shortfall assignment
  const [showShortfallAssignment, setShowShortfallAssignment] = useState(false);
  const [selectedPo, setSelectedPo] = useState<string | null>(null);
  const [selectedParts, setSelectedParts] = useState<Set<string>>(new Set());
  const [shortfalls, setShortfalls] = useState<Record<string, number>>({});
  const [expandedPo, setExpandedPo] = useState<Record<string, boolean>>({});

  const togglePoExpand = (partKey: string) => {
  setExpandedPo(prev => ({ ...prev, [partKey]: !prev[partKey] }));
};

  // Load build impact data
  useEffect(() => {
    setLoading(true);
    fetch(apiUrl(ApiEndpoints.build_impact))
      .then(async (res) => {
        const contentType = res.headers.get("Content-Type");
        if (!res.ok || !contentType?.includes("application/json")) {
          const text = await res.text();
          throw new Error(`Unexpected response: ${text}`);
        }
        return res.json();
      })
      .then((data: BuildImpactData) => {
        console.log('✅ Full Build Impact API Response:', data);
        setBuildData(data.results || []);
        setPendingPos(data.pending_pos || []);
        setError(null);
      })
      .catch((err) => {
        setError(err.message);
      })
      .finally(() => setLoading(false));
  }, []);

  // Toggle row expansion
  const toggleRowExpansion = (buildId: number) => {
    const newExpanded = new Set(expandedRows);
    if (newExpanded.has(buildId)) {
      newExpanded.delete(buildId);
    } else {
      newExpanded.add(buildId);
    }
    setExpandedRows(newExpanded);
  };

const getPartUrl = (id: number) => `/web/part/${id}/details`;
const getPoUrl   = (id: number) => `/web/purchasing/purchase-order/${id}/`;

  // Construct table columns for build summary
  const tableColumns: TableColumn[] = useMemo(() => {
    return [
      {
        accessor: 'expand',
        title: '',
        sortable: false,
        width: 40,
        render: (record: any) => (
          <ActionIcon
            variant="subtle"
            size="sm"
            onClick={() => toggleRowExpansion(record.build_id)}
          >
            {expandedRows.has(record.build_id) ? 
              <IconChevronDown size={16} /> : 
              <IconChevronRight size={16} />
            }
          </ActionIcon>
        )
      },
      {
        accessor: 'build_summary',
        title: t`Build Order`,
        sortable: true,
        render: (record: any) => (
          <div 
            style={{ cursor: 'pointer' }}
            onClick={() => toggleRowExpansion(record.build_id)}
          >
            <Group gap="md" wrap="nowrap">
              <div>
                <Text fw={500} size="sm">
                  {t`Build:`} {record.build}
                </Text>
                <Group gap="sm">
                  <Text 
                    size="xs" 
                    c={record.can_fulfill ? 'green' : 'red'}
                    fw={500}
                  >
                    {record.can_fulfill ? '✅ Can Fulfill' : '❌ Cannot Fulfill'}
                  </Text>
                  <Text size="xs" c="blue" fw={500}>
                    {t`Can Builds:`} {record.max_build_possible}
                  </Text>
                </Group>
              </div>
            </Group>
          </div>
        )
      },
      
    ];
  }, [expandedRows]);

  // Custom row renderer for expanded content
  const renderExpandedRow = (record: any) => {
    if (!expandedRows.has(record.build_id)) return null;

    const buildDetails = buildData.find(b => b.build_id === record.build_id);
    if (!buildDetails) return null;

    return (
      <tr>
        <td colSpan={2}>
          <Box p="md" style={{ backgroundColor: 'var(--mantine-color-gray-0)' }}>
            <Table striped withTableBorder withColumnBorders>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t`Part`}</Table.Th>
                  <Table.Th>{t`Required`}</Table.Th>
                  <Table.Th>{t`Available`}</Table.Th>
                  <Table.Th>{t`Purchased`}</Table.Th>
                  <Table.Th>{t`Virtual Stock`}</Table.Th>
                  <Table.Th>{t`Shortfall`}</Table.Th>
                  <Table.Th>{t`Status`}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {buildDetails.parts.map((part: PartData, idx: number) => (
                  <Table.Tr key={idx}>
                    <Table.Td>
                      <Text fw={500}>{part.part?.name || 'Unknown Part'}</Text>
                    </Table.Td>
                    <Table.Td>{part.required}</Table.Td>
                    <Table.Td>
                      {part.available_stock} / {part.available_stock_total}
                    </Table.Td>
                    <Table.Td>
                      {part.incoming_stock} / {part.incoming_stock_total}
                    </Table.Td>
                    <Table.Td>{part.virtual_stock}</Table.Td>
                    <Table.Td>
                      <Text c={part.shortfall > 0 ? 'red' : 'gray'}>
                        {part.shortfall > 0 ? part.shortfall : 0}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text c={part.can_fulfill ? 'green' : 'red'} fw={500}>
                        {part.can_fulfill ? t`Sufficient` : t`Insufficient`}
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Box>
        </td>
      </tr>
    );
  };

  // Table actions
  const tableActions = useMemo(() => {
    const can_manage = user.hasChangeRole(UserRoles.purchase_order);
    
    return [
      <Button
        key="show-shortfall-assignment"
        color="yellow"
        leftSection={<IconAlertCircle size={16} />}
        onClick={() => setShowShortfallAssignment(!showShortfallAssignment)}
        disabled={!can_manage}
      >
        {t`Assign Shortfalls`}
      </Button>
    ];
  }, [user, showShortfallAssignment]);

  // Shortfall assignment functions
  const toggleSelected = (key: string) => {
    const updated = new Set(selectedParts);
    if (updated.has(key)) updated.delete(key);
    else updated.add(key);
    setSelectedParts(updated);
  };

  const updateShortfall = (key: string, value: number) => {
    setShortfalls((prev) => ({ ...prev, [key]: value }));
  };

  const handleAssignShortfalls = () => {
    const payloadShortfalls: Record<string, number> = {};

    // Include actual shortfall values
    buildData.forEach((build) => {
      build.parts
        .filter((p: any) => p.shortfall > 0 && p.part?.id)
        .forEach((p: any) => {
          const key = `${build.build_id}::${p.part.id}`;
          payloadShortfalls[key] = shortfalls[key] ?? p.shortfall;
        });
    });

    api.post(ApiEndpoints.assign_shortfalls, {
      selected_po: selectedPo,
      selected_parts: Array.from(selectedParts),
      ...Object.fromEntries(
        Object.entries(payloadShortfalls).map(([key, val]) => [
          `shortfall_${key.replace("::", "_")}`,
          val,
        ])
      ),
    })
      .then((res) => {
        alert('✅ Shortfalls assigned successfully!');
        setShowShortfallAssignment(false);
        setSelectedParts(new Set());
        setSelectedPo(null);
        setShortfalls({});
      })
      .catch((err) => {
        console.error(err);
        alert('❌ Failed to assign shortfalls.');
      });
  };

  if (error) {
    return (
      <Alert icon={<IconAlertCircle size={16} />} title={t`Error`} color="red">
        {t`Failed to load build impact report.`} <br />
        <Text size="xs" mt="xs" c="dimmed">{error}</Text>
      </Alert>
    );
  }

  const shortfallData = useMemo(() => {
    return buildData.flatMap((build) =>
      build.parts
        .filter((p: any) => p.shortfall > 0 && p.part?.id)
        .map((p: any) => ({
          key: `${build.build_id}::${p.part.id}`,
          build_name: build.build,
          part_name: p.part.name,
          shortfall: p.shortfall
        }))
    );
  }, [buildData]);

  if (loading) {
    return (
      <Group justify="center" mt="xl">
        <Text>{t`Loading Build Impact Report...`}</Text>
      </Group>
    );
  }

  if (buildData.length === 0) {
    return (
      <Alert color="yellow" icon={<IconAlertCircle size={16} />}>
        {t`No build orders found.`}
      </Alert>
    );
  }

  return (
    <Stack>
      {/* Main Table */}
<Table striped withTableBorder withColumnBorders highlightOnHover>
  <Table.Thead>
    <Table.Tr>
      <Table.Th style={{ width: 40 }}></Table.Th>
      <Table.Th>{t`Build Order`}</Table.Th>
      <Table.Th>{t`Status`}</Table.Th>
      <Table.Th>{t`Can Build`}</Table.Th>
    </Table.Tr>
  </Table.Thead>
  <Table.Tbody>
    {buildData.map((build) => (
      <React.Fragment key={build.build_id}>
        {/* Main row */}
        <Table.Tr>
          <Table.Td>
            <ActionIcon
              variant="subtle"
              size="sm"
              onClick={() => toggleRowExpansion(build.build_id)}
            >
              {expandedRows.has(build.build_id) ? (
                <IconChevronDown size={16} />
              ) : (
                <IconChevronRight size={16} />
              )}
            </ActionIcon>
          </Table.Td>
          <Table.Td
            style={{ cursor: 'pointer' }}
            onClick={() => toggleRowExpansion(build.build_id)}
          >
            {build.build}
          </Table.Td>
          <Table.Td>
            <Text c={build.can_fulfill ? 'green' : 'red'} fw={500}>
              {build.can_fulfill ? t`Sufficient` : t`Insufficient`}
            </Text>
          </Table.Td>
          <Table.Td>
            <Text c="blue" fw={500}>
              {build.max_build_possible}
            </Text>
          </Table.Td>
        </Table.Tr>

        {/* Expanded row (single TR, spans across all columns) */}
        {expandedRows.has(build.build_id) && (
          <Table.Tr>
            <Table.Td colSpan={4}>
              <Box
                p="md"
                style={{ backgroundColor: 'var(--mantine-color-gray-0)' }}
              >
                <Table striped withTableBorder withColumnBorders>
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th>{t`PO`}</Table.Th>
                        <Table.Th>{t`Part`}</Table.Th>
                        <Table.Th>{t`Description`}</Table.Th>
                        <Table.Th>{t`Required`}</Table.Th>
                        <Table.Th>{t`Available`}</Table.Th>
                        <Table.Th>{t`Purchased`}</Table.Th>
                        <Table.Th>{t`Virtual Stock`}</Table.Th>
                        <Table.Th>{t`Receive Date`}</Table.Th>  {/* ⭐ NEW COLUMN */}
                        <Table.Th>{t`Shortfall`}</Table.Th>
                        <Table.Th>{t`Status`}</Table.Th>
                      </Table.Tr>
                    </Table.Thead>
                  <Table.Tbody>
                    {build.parts.map((part: PartData, idx: number) => {
                      const partKey = `${build.build_id}_${idx}`;
                      const poList = part.po_list || [];
                      const firstPo = poList[0];
                      const extraPos = poList.slice(1);

                      return (
                        <React.Fragment key={idx}>

                          {/* ⭐ Main displayed row */}
                          <Table.Tr>
                            <Table.Td>
                              <a href={getPoUrl(firstPo?.id ?? 0)} style={{ color: 'var(--mantine-color-blue-7)', textDecoration: 'underline' }}>
                                #{firstPo?.reference}
                              </a>

                              {extraPos.length > 0 && (
                                <Text
                                  size="xs"
                                  style={{ cursor: "pointer", color: "var(--mantine-color-blue-7)" }}
                                  onClick={() => togglePoExpand(partKey)}
                                >
                                  {expandedPo[partKey] ? "▲ Hide" : `+${extraPos.length} more`}
                                </Text>
                              )}
                            </Table.Td>

                            {/* Part info */}
                            <Table.Td>
                              <a href={getPartUrl(part.part?.id ?? 0)} style={{textDecoration:'underline', color:'var(--mantine-color-blue-7)'}}>
                                {part.part?.name}
                              </a>
                            </Table.Td>

                            <Table.Td>{part.part?.description ?? '—'}</Table.Td>
                            <Table.Td>{part.required}</Table.Td>
                            <Table.Td>{part.available_stock} / {part.available_stock_total}</Table.Td>
                            <Table.Td>{part.incoming_stock} / {part.incoming_stock_total}</Table.Td>
                            <Table.Td>{part.virtual_stock}</Table.Td>
                            {/* ⭐ Receive Date column */}
                            <Table.Td>
                              {!firstPo ? (
                                <Text size="xs" c="dimmed">—</Text>   // No PO for this part
                              ) : firstPo.received_date ? (
                                <Text c="green">{firstPo.received_date}</Text>   // PO received
                              ) : (
                                <Text c="orange">Pending</Text>   // PO exists but not received
                              )}
                            </Table.Td>

                            <Table.Td>
                              <Text c={part.shortfall > 0 ? 'red' : 'gray'} fw={500}>
                                {part.shortfall || 0}
                              </Text>
                            </Table.Td>

                            <Table.Td>
                              <Text c={part.can_fulfill ? 'green' : 'red'}>
                                {part.can_fulfill ? t`Sufficient` : t`Insufficient`}
                              </Text>
                            </Table.Td>
                          </Table.Tr>

                          {/* ⭐ Expanded additional PO rows */}
                          {expandedPo[partKey] &&
                            extraPos.map((po, i) => (
                              <Table.Tr key={i} style={{ background: "#f8f9fa" }}>
                                <Table.Td>
                                  <a href={getPoUrl(po.id ?? 0)} style={{ color: 'var(--mantine-color-blue-7)', textDecoration: 'underline' }}>
                                    #{po.reference}
                                  </a>
                                </Table.Td>

                                {/* Empty columns to align */}
                                <Table.Td colSpan={4}></Table.Td>
                                <Table.Td>{po.quantity}</Table.Td>

                                {/* ⭐ Receive Date */}
                                <Table.Td>
                                  {po.received_date ? (
                                    <Text c="green">{po.received_date}</Text>
                                  ) : (
                                    <Text c="orange">Pending</Text>
                                  )}
                                </Table.Td>

                                <Table.Td colSpan={2}></Table.Td>
                              </Table.Tr>
                            ))}
                        </React.Fragment>
                      );
                    })}
                  </Table.Tbody>
                </Table>
              </Box>
            </Table.Td>
          </Table.Tr>
        )}
      </React.Fragment>
    ))}
  </Table.Tbody>
</Table>


      {/* Table Actions */}
      <Group justify="flex-end">
        {user.hasChangeRole(UserRoles.purchase_order) && (
          <Button
            color="yellow"
            leftSection={<IconAlertCircle size={16} />}
            onClick={() => setShowShortfallAssignment(!showShortfallAssignment)}
          >
            {t`Assign Shortfalls`}
          </Button>
        )}
      </Group>

      {/* Shortfall Assignment Section */}
<Collapse in={showShortfallAssignment}>
  <Paper withBorder shadow="xs" p="md" mt="md">
    <Title order={4} mb="sm">
      {t`Assign Shortfalls to Purchase Order`}
    </Title>

    <Select
      label={t`Select Pending Purchase Order`}
      placeholder={t`Choose...`}
      data={pendingPos.map((po: PendingPO) => ({
        value: String(po.id),
        label: `#${po.reference} — ${po.supplier__name} — ${po.target_date}`
      }))}
      value={selectedPo}
      onChange={setSelectedPo}
      required
      mb="md"
    />

    {shortfallData.length > 0 ? (
      <>
        <Group mb="md">
          <Checkbox
            label={t`Select All`}
            onChange={(e) => {
              const checked = e.currentTarget.checked;
              const allKeys = shortfallData.map((item) => item.key);
              setSelectedParts(new Set(checked ? allKeys : []));
            }}
          />
        </Group>

        {/* Table instead of Stack */}
        <Table striped withTableBorder withColumnBorders highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th style={{ width: 50 }}></Table.Th>
              <Table.Th>{t`Build`}</Table.Th>
              <Table.Th>{t`Part`}</Table.Th>
              <Table.Th style={{ width: 120 }}>{t`Shortfall`}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {shortfallData.map((item) => (
              <Table.Tr key={item.key}>
                <Table.Td>
                  <Checkbox
                    checked={selectedParts.has(item.key)}
                    onChange={() => toggleSelected(item.key)}
                  />
                </Table.Td>
                <Table.Td>
                  <Text size="sm" fw={500}>
                    {item.build_name}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{item.part_name}</Text>
                </Table.Td>
                <Table.Td>
                  <NumberInput
                    size="xs"
                    w={100}
                    min={0}
                    value={shortfalls[item.key] ?? item.shortfall}
                    onChange={(val) => updateShortfall(item.key, Number(val))}
                  />
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>

        <Group mt="md" justify="flex-end">
          <Button
            variant="outline"
            onClick={() => {
              setShowShortfallAssignment(false);
              setSelectedParts(new Set());
              setSelectedPo(null);
              setShortfalls({});
            }}
          >
            {t`Cancel`}
          </Button>
          <Button
            onClick={handleAssignShortfalls}
            disabled={!selectedPo || selectedParts.size === 0}
          >
            {t`Assign to Purchase Order`}
          </Button>
        </Group>
      </>
    ) : (
      <Alert color="blue" icon={<IconAlertCircle size={16} />}>
        {t`No shortfalls found to assign.`}
      </Alert>
    )}
  </Paper>
</Collapse>

    </Stack>
  );
}

export default function BuildImpactReport() {
  return <BuildImpactTable />;
}