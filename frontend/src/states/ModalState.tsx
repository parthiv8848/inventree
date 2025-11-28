import { create } from 'zustand';
import { AddItemButton } from '../components/buttons/AddItemButton';// Assuming StandaloneField is 

interface ModalStateProps {
  openModals: Record<string, boolean>;
  isModalOpen: (modalKey: string) => boolean;
  setModalOpen: (modalKey: string, isOpen: boolean) => void;
}

/**
 * Global state manager for determining modal visibility.
 * Useful to share modal state (open / closed) between components.
 */
export const useModalState = create<ModalStateProps>()((set, get) => ({
  openModals: {},

  isModalOpen: (modalKey: string) => {
    return get().openModals[modalKey] ?? false;
  },

  setModalOpen: (modalKey: string, isOpen: boolean) => {
    set((state) => ({
      openModals: {
        ...state.openModals,
        [modalKey]: isOpen
      }
    }));
  }
}));


export function openModal(modal: any, getInitialData?: () => any) {
  return {
    field_type: 'custom',
    label: '',
    description: '',
    render: () => (
      <div
        style={{
          position: 'relative',
          marginTop: '-85px',
          marginBottom: '16px',
          display: 'flex',
          justifyContent: 'flex-end',
          paddingRight: '4px',
        }}
      >
        <AddItemButton
          tooltip={modal.modal?.props?.title?.props?.children ?? `Add New`}
          onClick={() =>
            modal.open({
              initialData: getInitialData ? getInitialData() : {}
            })
          }
        />
      </div>
    ),
  };
}
