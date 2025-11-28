import { t } from '@lingui/core/macro';
import { Grid, Skeleton, Stack, Loader, Alert, Button, Modal, TextInput, Textarea, Group, Select, MultiSelect } from '@mantine/core';
import { useMemo, useEffect, useState } from 'react';
import { useNavigate, useParams, Link } from 'react-router-dom';
import { api } from '../../App'; // axios instance

import PrimaryActionButton from '../../components/buttons/PrimaryActionButton';
import { PageDetail } from '../../components/nav/PageDetail';
import { IconAlertCircle } from "@tabler/icons-react";
import { UserRoles } from '@lib/enums/Roles';
import { useUserState } from '../../states/UserState';

interface Project {
  id: number;
  name: string;
  description?: string;
  created_date: string;
  status: string;
  users?: number[];
  parts?: number[];
  barcode_hash?: string;
}

interface User {
  id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
}

interface Part {
  id: number;
  name: string;
  description?: string;
  part_number: string;
}

// Enhanced ProjectList component with both list and detail functionality
export default function ProjectList() { 
  const [projects, setProjects] = useState<Project[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [parts, setParts] = useState<Part[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [editProject, setEditProject] = useState<Project | null>(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [selectedUsers, setSelectedUsers] = useState<string[]>([]);
  const [selectedParts, setSelectedParts] = useState<string[]>([]);
  const [status, setStatus] = useState<string>('active');
  const [partsPage, setPartsPage] = useState(0);
  const [partsHasMore, setPartsHasMore] = useState(true);
  const [partsLoading, setPartsLoading] = useState(false);
  const [partSearch, setPartSearch] = useState('');

  const user = useUserState();

//   useEffect(() => {
//   console.log("🔐 Project Permissions:");
//   console.log("Can VIEW:", user.hasViewRole(UserRoles.project));
//   console.log("Can CREATE:", user.hasAddRole(UserRoles.project));
//   console.log("Can EDIT:", user.hasChangeRole(UserRoles.project));
//   console.log("Can DELETE:", user.hasDeleteRole(UserRoles.project));
// }, [user]);

const fetchProjects = () => {
  setLoading(true);

  api.get('/api/part/project/')
    .then(res => {
      console.log('Raw project API response:', res.data);

      // If your API is paginated, it might have res.data.results
      const data = res.data?.results || res.data || [];
      console.log('Processed project list for state:', data);

      setProjects(Array.isArray(data) ? data : []);
    })
    .catch(err => {
      console.error('Failed to load projects:', err);
      setError(err.message || 'Failed to load projects');
    })
    .finally(() => setLoading(false));
};

  const fetchUsers = () => {
    api.get('/api/user/')
      .then(res => {
        console.log('Raw user API response:', res.data);

        // If API is paginated and returns { results: [...] }
        const data = res.data?.results || res.data || [];
        console.log('Processed user list for state:', data);

        setUsers(Array.isArray(data) ? data : []);
      })
      .catch(err => {
        console.error('Failed to load users:', err);
      });
  };

const fetchParts = (page = 0, search = '') => {
  if (partsLoading || (!partsHasMore && page > 0)) return;

  setPartsLoading(true);

  api.get('/api/part/', {
    params: {
      limit: 10,
      offset: page * 10,
      search, // pass search query to backend
    },
  })
  .then(res => {
    const data = res.data?.results || res.data || [];
    if (page === 0) {
      // new search → replace results
      setParts(Array.isArray(data) ? data : []);
    } else if (Array.isArray(data) && data.length > 0) {
      setParts(prev => [...prev, ...data]);
    } else {
      setPartsHasMore(false);
    }
    setPartsPage(page);
  })
  .catch(err => console.error('Failed to load parts:', err))
  .finally(() => setPartsLoading(false));
};

  useEffect(() => {
    fetchProjects();
    fetchUsers();
    fetchParts(0);
  }, []);

  const handleOpenModal = (project?: Project | null) => {
    if (project) {
      setEditProject(project);
      setName(project.name);
      setDescription(project.description || '');
      setStatus(project.status || 'active');
      setSelectedUsers(project.users?.map((id: number) => id.toString()) || []);
      setSelectedParts(project.parts?.map((id: number) => id.toString()) || []);
    } else {
      setEditProject(null);
      setName('');
      setDescription('');
      setStatus('active');
      setSelectedUsers([]);
      setSelectedParts([]);
    }
    setModalOpen(true);
  };

  const handleSave = () => {
    const payload = {
      name,
      description,
      status,
      users: selectedUsers.map(id => parseInt(id)),  // match ManyToMany field name
      parts: selectedParts.map(id => parseInt(id))   // match ManyToMany field name
    };

    console.log('Project payload to save:', payload);

    if (editProject) {
      api.put(`/api/part/project/${editProject.id}/`, payload)
        .then(() => {
          fetchProjects();
          setModalOpen(false);
        })
        .catch(err => setError(err.message || 'Failed to update project'));
    } else {
      api.post('/api/part/project/', payload)
        .then(() => {
          fetchProjects();
          setModalOpen(false);
        })
        .catch(err => setError(err.message || 'Failed to create project'));
    }
  };


  const handleDelete = (id: number) => {
    if (!confirm('Are you sure you want to delete this project?')) return;
    api.delete(`/api/part/project/${id}/`)
      .then(() => fetchProjects())
      .catch(err => setError(err.message || 'Failed to delete project'));
  };

// Deduplicate users by id (fallback: tmp-{index})
const uniqueUsers = Array.from(
  new Map(
    (Array.isArray(users) ? users : []).map((user, idx) => [
      user.id ?? (user as any).pk ?? (user as any).user_id ?? `tmp-user-${idx}`,
      user
    ])
  ).values()
);

const userOptions = uniqueUsers.map(user => ({
  value: String(user.id ?? (user as any).pk ?? (user as any).user_id),
  label: `${user.first_name ?? ''} ${user.last_name ?? ''} (${user.email ?? ''})`
}));

// Deduplicate parts by id (fallback: tmp-{index})
const uniqueParts = Array.from(
  new Map(
    (Array.isArray(parts) ? parts : []).map((part, idx) => [
      part.id ?? (part as any).pk ?? (part as any).part_id ?? `tmp-part-${idx}`,
      part
    ])
  ).values()
);

const partOptions = uniqueParts.map(part => ({
  value: String(part.id ?? (part as any).pk ?? (part as any).part_id),
  label: `${part.name ?? ''} - ${part.description ?? ''}`
}));


console.log("✅ Deduped userOptions:", userOptions);
console.log("✅ Deduped partOptions:", partOptions);


  const statusOptions = [
    { value: 'active', label: 'Active' },
    { value: 'inactive', label: 'Inactive' },
    { value: 'completed', label: 'Completed' },
    { value: 'cancelled', label: 'Cancelled' }
  ];

  if (loading) return <Loader />;

  return (
    <div>
      <PageDetail
        title={t`Projects`}
        actions={[
          <PrimaryActionButton
            key='create'
            title={t`Create Project`}
            icon='add'
            onClick={() => handleOpenModal()}
            hidden={!user.hasAddRole(UserRoles.project)}
          />
        ]}
      />
      
      {error && (
        <Alert icon={<IconAlertCircle size={16} />} title="Error" color="red" mb="md">
          {error}
        </Alert>
      )}

      {!user.hasViewRole(UserRoles.project) ? (
        <Alert icon={<IconAlertCircle size={16} />} color="red" mt="md">
          {t`You do not have permission to view projects.`}
        </Alert>
      ) : projects.length === 0 ? (
        <Alert icon={<IconAlertCircle size={16} />} color="blue" mt="md">
          {t`No projects available.`}
        </Alert>
      ) : (

      <div style={{ display: 'grid', gap: '16px' }}>
        {projects.map(project => (
          <div key={project.id} style={{
            border: '1px solid #e0e0e0',
            borderRadius: '8px',
            padding: '16px',
            backgroundColor: 'white'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div style={{ flex: 1 }}>
                <h3 style={{ margin: '0 0 8px 0' }}>
                  <button
                      onClick={() => {
                        window.location.href = `/web/project/${project.id}/`;
                      }}
                    style={{
                      background: 'none',
                      border: 'none',
                      color: '#1976d2',
                      cursor: 'pointer',
                      fontSize: 'inherit',
                      fontWeight: 'inherit',
                      textDecoration: 'underline'
                    }}
                  >
                    {project.name}
                  </button>
                </h3>
                <p style={{ margin: '0 0 8px 0', color: '#666' }}>
                  {project.description || 'No description'}
                </p>
                <div style={{ display: 'flex', gap: '16px', fontSize: '14px', color: '#888' }}>
                  {/* <span>Status: {project.status?.toUpperCase()}</span> */}
                  <span>Users: {project.users?.length || 0}</span>
                  <span>Parts: {project.parts?.length || 0}</span>
                </div>
              </div>
              <div style={{ display: 'flex', gap: '8px' }}>
                <PrimaryActionButton
                  key="edit"
                  title={t`Edit Project`}
                  icon="edit"
                  onClick={() => handleOpenModal(project)}
                  hidden={!user.hasChangeRole(UserRoles.project)}
                />
                <PrimaryActionButton
                  key="delete"
                  title={t`Delete Project`}
                  icon="delete"
                  color="red"
                  onClick={() => handleDelete(project.id)}
                  hidden={!user.hasDeleteRole(UserRoles.project)}
                />

              </div>
            </div>
          </div>
        ))}
      </div>
      )}

      <Modal
        opened={modalOpen}
        onClose={() => setModalOpen(false)}
        title={editProject ? 'Edit Project' : 'Create Project'}
        size="lg"
      >
        <Stack gap="md">
          <TextInput
            label="Name"
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            required
          />
          <Textarea
            label="Description"
            value={description}
            onChange={(e) => setDescription(e.currentTarget.value)}
            rows={3}
          />
          <Select
            label="Status"
            value={status}
            onChange={(value) => setStatus(value || 'active')}
            data={statusOptions}
          />
          <MultiSelect
            label="Assign Users"
            value={selectedUsers}
            onChange={setSelectedUsers}
            data={userOptions}
            searchable
            placeholder="Select users to assign"
          />
          <MultiSelect
            label="Assign Parts"
            value={selectedParts}
            onChange={setSelectedParts}
            data={partOptions}
            searchable
            searchValue={partSearch}
            onSearchChange={(query) => {
              setPartSearch(query);
              setPartsPage(0);
              setPartsHasMore(true);
              fetchParts(0, query); // fetch fresh results with search
            }}
            placeholder="Select parts to assign"
            nothingFoundMessage="No parts found"
            rightSection={partsLoading ? <Loader size="xs" /> : null}
            scrollAreaProps={{
              style: { maxHeight: 200 },
              onScrollPositionChange: ({ y }) => {
                const el = document.querySelector('.mantine-ScrollArea-viewport') as HTMLElement;
                if (
                  el &&
                  y + el.clientHeight >= el.scrollHeight - 10 &&
                  !partsLoading &&
                  partsHasMore
                ) {
                  fetchParts(partsPage + 1, partSearch); // fetch next page with current search
                }
              },
            }}
          />
          <Group justify="flex-end">
            <Button onClick={handleSave}>
              {editProject ? 'Update' : 'Create'}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </div>
  );
}