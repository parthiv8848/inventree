import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Card, Title, Text, Table, Loader, Alert } from "@mantine/core";
import { api } from '../../App';

interface User {
  id: number;
  username: string;
  email?: string;
}

interface Part {
  id: number;
  name: string;
  description?: string;
}

interface Project {
  id: number;
  name: string;
  description: string;
  pathstring: string;
  users: number[]; // raw IDs
  parts: number[]; // raw IDs
  assigned_users?: User[];
  part_details?: Part[];
}

export default function ProjectDetail() {
  const { id } = useParams<{ id: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);

    api
      .get(`/api/part/project/${id}/`)
      .then(async (res) => {
        const projectData: Project = res.data;

        // fetch user details
        const users = await Promise.all(
          (projectData.users || []).map((uid) =>
            api
              .get(`/api/user/${uid}/`)
              .then((r) => r.data)
              .catch(() => null)
          )
        );

        // fetch part details
        const parts = await Promise.all(
          (projectData.parts || []).map((pid) =>
            api
              .get(`/api/part/${pid}/`)
              .then((r) => r.data)
              .catch(() => null)
          )
        );

        setProject({
          ...projectData,
          assigned_users: users.filter(Boolean),
          part_details: parts.filter(Boolean),
        });
      })
      .catch((err) =>
        setError(err.message || "Failed to load project details")
      )
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <Loader />;
  if (error) return <Alert color="red">{error}</Alert>;
  if (!project) return <Alert>No project found</Alert>;

  return (
    <div className="p-6 space-y-6">
      {/* Project Info */}
      <Card shadow="sm" p="lg" radius="md" withBorder>
        <Title order={2}>{project.name}</Title>
        <Text c="dimmed" mb="md">
          {project.description || "No description"}
        </Text>

        <Text fw={500}>Path:</Text>
        <Text mb="md">{project.pathstring}</Text>
      </Card>

      {/* Assigned Users */}
      <Card shadow="sm" p="lg" radius="md" withBorder>
        <Title order={3} mb="md">
          Assigned Users
        </Title>
        {project.assigned_users?.length ? (
          <Table striped highlightOnHover withTableBorder>
            <Table.Thead>
              <Table.Tr>
                {/* <Table.Th>ID</Table.Th> */}
                <Table.Th>Username</Table.Th>
                <Table.Th>Email</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {project.assigned_users.map((u) => (
                <Table.Tr key={u.id}>
                  {/* <Table.Td>{u.id}</Table.Td> */}
                  <Table.Td>{u.username}</Table.Td>
                  <Table.Td>{u.email || "-"}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        ) : (
          <Text>No users assigned</Text>
        )}
      </Card>

      {/* Related Parts */}
      <Card shadow="sm" p="lg" radius="md" withBorder>
        <Title order={3} mb="md">
          Related Parts
        </Title>
        {project.part_details?.length ? (
          <Table striped highlightOnHover withTableBorder>
            <Table.Thead>
              <Table.Tr>
                {/* <Table.Th>ID</Table.Th> */}
                <Table.Th>Name</Table.Th>
                <Table.Th>Description</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {project.part_details.map((p) => (
                <Table.Tr key={p.id}>
                  {/* <Table.Td>{p.id}</Table.Td> */}
                  <Table.Td>{p.name}</Table.Td>
                  <Table.Td>{p.description || "-"}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        ) : (
          <Text>No parts linked</Text>
        )}
      </Card>
    </div>
  );
}
 