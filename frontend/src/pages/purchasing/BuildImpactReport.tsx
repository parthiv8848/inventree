import {
  Accordion,
  Alert,
  Button,
  Checkbox,
  Collapse,
  Group,
  Loader,
  NumberInput,
  Paper,
  Select,
  Stack,
  Table,
  Text,
  Title
} from '@mantine/core';
import { IconAlertCircle } from '@tabler/icons-react';
import { useEffect, useState } from 'react';
import { t } from '@lingui/macro';
import { ApiEndpoints } from '@lib/enums/ApiEndpoints';
import { apiUrl } from '@lib/functions/Api';
// Update the import path below to the correct location of your api instance:
import { api } from '../../App'; // adjust the path as needed

export default function BuildImpactReport() {
  const [results, setResults] = useState<any[]>([]);
  const [pendingPos, setPendingPos] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCollapse, setShowCollapse] = useState(false);
  const [selectedPo, setSelectedPo] = useState<string | null>(null);
  const [selectedParts, setSelectedParts] = useState<Set<string>>(new Set());
  const [shortfalls, setShortfalls] = useState<Record<string, number>>({});

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
      .then((data) => {
        console.log('✅ Full Build Impact API Response:', data);

        if (!data.results || !Array.isArray(data.results)) {
          console.warn('⚠️ Missing or invalid `results` in API response');
        }

        if (!data.pending_pos || !Array.isArray(data.pending_pos)) {
          console.warn('⚠️ Missing or invalid `pending_pos` in API response');
        }

        setResults(data.results || []);
        setPendingPos(data.pending_pos || []);
      })
      .catch((err) => {
        setError(err.message);
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <Group justify="center" mt="xl">
        <Loader size="lg" />
        <Text>{t`Loading Build Impact Report...`}</Text>
      </Group>
    );
  }

  if (error) {
    return (
      <Alert icon={<IconAlertCircle size={16} />} title={t`Error`} color="red">
        {t`Failed to load build impact report.`} <br />
        <Text size="xs" mt="xs" color="dimmed">{error}</Text>
      </Alert>
    );
  }

  const toggleSelected = (key: string) => {
    const updated = new Set(selectedParts);
    if (updated.has(key)) updated.delete(key);
    else updated.add(key);
    setSelectedParts(updated);
  };

  const updateShortfall = (key: string, value: number) => {
    setShortfalls((prev) => ({ ...prev, [key]: value }));
  };

  return (
    <Stack>
      {/* <Title order={2}>{t`Build Impact Report`}</Title> */}

      {results.length === 0 ? (
        <Alert color="yellow" icon={<IconAlertCircle size={16} />}>
          {t`No build orders found.`}
        </Alert>
      ) : (
        <Accordion multiple defaultValue={[]}>
          {results.map((build, idx) => (
            <Accordion.Item key={idx} value={`build-${idx}`}>
              <Accordion.Control>
                <Group justify="space-between" grow>
                  <Text>
                    <strong>{t`Build`}:</strong> {build.build}
                  </Text>
                  <Text color={build.can_fulfill ? 'green' : 'red'}>
                    {build.can_fulfill ? '✅ Can Fulfill' : '❌ Cannot Fulfill'}
                  </Text>
                  <Text>{t`Can Builds:`} {build.max_build_possible}</Text>
                </Group>
              </Accordion.Control>
              <Accordion.Panel>
                <Table striped withColumnBorders highlightOnHover>
                  <thead>
                    <tr>
                      <th>{t`Part`}</th>
                      <th>{t`Required`}</th>
                      <th>{t`Available`}</th>
                      <th>{t`Purchased`}</th>
                      <th>{t`Virtual Stock`}</th>
                      <th>{t`Shortfall`}</th>
                      <th>{t`Status`}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {build.parts.map((part: any, idx2: number) => {
                      const shortfall = part.shortfall;
                      const status = part.can_fulfill ? 'Sufficient' : 'Insufficient';
                      return (
                        <tr key={idx2}>
                          <td><strong>{part.part?.name}</strong></td>
                          <td>{part.required}</td>
                          <td>{part.available_stock} / {part.available_stock_total}</td>
                          <td>{part.incoming_stock} / {part.incoming_stock_total}</td>
                          <td>{part.virtual_stock}</td>
                          <td style={{ color: shortfall > 0 ? 'red' : 'gray' }}>
                            {shortfall > 0 ? shortfall : 0}
                          </td>
                          <td>
                            <Text color={part.can_fulfill ? 'green' : 'red'}>
                              {part.can_fulfill ? t`Sufficient` : t`Insufficient`}
                            </Text>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </Table>
              </Accordion.Panel>
            </Accordion.Item>
          ))}
        </Accordion>
      )}

      <Button
        color="yellow"
        onClick={() => setShowCollapse(!showCollapse)}
        mt="xl"
      >
        🚨 {t`Show All Insufficient Parts`}
      </Button>

      <Collapse in={showCollapse}>
        <Paper withBorder shadow="xs" p="md" mt="md">
          <Title order={4} mb="sm">{t`Assign Shortfalls to Purchase Order`}</Title>
          <Select
            label={t`Select Pending Purchase Order`}
            placeholder={t`Choose...`}
            data={pendingPos.map((po: any) => ({
              value: String(po.id),
              label: `#${po.reference} — ${po.supplier__name} — ${po.target_date}`
            }))}
            value={selectedPo}
            onChange={setSelectedPo}
            required
          />

          <Table striped withColumnBorders mt="md">
            <thead>
              <tr>
                <th>
                  <Checkbox
                    onChange={(e) => {
                      const checked = e.currentTarget.checked;
                      const allIds = results.flatMap((build) =>
                        build.parts
                          .filter((p: any) => p.shortfall > 0)
                          .map((p: any) => `${build.build_id}::${p.part?.id}`)
                      );
                      setSelectedParts(new Set(checked ? allIds : []));
                    }}
                  />
                </th>
                <th>{t`Build`}</th>
                <th>{t`Part`}</th>
                <th>{t`Shortfall`}</th>
              </tr>
            </thead>
            <tbody>
              {results.map((build) =>
                build.parts
                  .filter((p: any) => p.shortfall > 0 && p.part?.id)
                  .map((p: any, i: number) => {
                    const key = `${build.build_id}::${p.part.id}`;
                    return (
                      <tr key={key}>
                        <td>
                          <Checkbox
                            checked={selectedParts.has(key)}
                            onChange={() => toggleSelected(key)}
                          />
                        </td>
                        <td>{build.build}</td>
                        <td>{p.part.name}</td>
                        <td>
                          <NumberInput
                            size="xs"
                            min={0}
                            value={shortfalls[key] ?? p.shortfall}
                            onChange={(val) => updateShortfall(key, Number(val))}
                          />
                        </td>
                      </tr>
                    );
                  })
              )}
            </tbody>
          </Table>

          <Group mt="md" justify="flex-end">
            <Button
              onClick={() => {
                const payloadShortfalls: Record<string, number> = {};

                // Always include actual shortfall values, even if user hasn't edited them
                results.forEach((build) => {
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
                  })
                  .catch((err) => {
                    console.error(err);
                    alert('❌ Failed to assign shortfalls.');
                  });
              }}
              disabled={!selectedPo || selectedParts.size === 0}
            >
              {t`Assign to Purchase Order`}
            </Button>

          </Group>
        </Paper>
      </Collapse>
    </Stack>
  );
}
