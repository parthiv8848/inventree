import { useEffect, useState } from "react";
import { Card, Table, Text, Group, Button, Skeleton } from "@mantine/core";
import { IconEye } from "@tabler/icons-react";
import { useNavigate } from "react-router-dom";
import { api } from "../../App";

interface Project {
  id: number;
  name: string;
  description: string;
}

export default function PartProjectsPanel({ partId }: { partId: number }) {
  const navigate = useNavigate();

  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!partId) return;

    setLoading(true);
    api
      .get(`/api/part/${partId}/projects/`) // <-- Your endpoint
      .then((res) => setProjects(res.data))
      .catch((err) =>
        setError(err.message || "Failed to load projects for this part")
      )
      .finally(() => setLoading(false));
  }, [partId]);

  if (loading) return <Skeleton height={200} radius="md" />;
  if (error) return <Text c="red">{error}</Text>;
  if (!projects.length) return <Text>No projects linked to this part.</Text>;

  return (
    <Card shadow="sm" p="md" radius="md" withBorder>
      <Text fw={600} size="lg" mb="sm">
        Projects using this Part
      </Text>

      <Table highlightOnHover withColumnBorders>
        <thead>
          <tr>
            <th style={{ textAlign: "center" }}>ID</th>
            <th style={{ textAlign: "center" }}>Project Name</th>
            <th style={{ textAlign: "center" }}>Description</th>
            <th style={{ textAlign: "center" }}>Action</th>
          </tr>
        </thead>
        <tbody>
          {projects.map((proj) => (
            <tr key={proj.id}>
              <td style={{ textAlign: "center" }}>{proj.id}</td>
              <td style={{ textAlign: "center" }}>{proj.name}</td>
              <td style={{ textAlign: "center" }}>
                {proj.description || "—"}
              </td>
              <td style={{ textAlign: "center" }}>
                <Group justify="center">
                  <Button
                    size="xs"
                    variant="light"
                    leftSection={<IconEye size={16} />}
                    onClick={() => navigate(`/project/${proj.id}/`)}
                  >
                    View
                  </Button>
                </Group>
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  );
}
 