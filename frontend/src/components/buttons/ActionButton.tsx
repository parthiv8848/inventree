import { ActionIcon, Tooltip, Group, Loader } from '@mantine/core';
import { identifierString } from '../../functions/conversion';

export interface ActionButtonProps {
  tooltip?: string;
  text?: string;
  icon?: React.ReactNode;
  color?: string;
  size?: any;
  radius?: any;
  variant?: any;
  disabled?: boolean;
  hidden?: boolean;
  loading?: boolean;              // NEW
  tooltipAlignment?: 'left' | 'right' | 'top' | 'bottom';
  onClick?: (event: any) => void;
}

export function ActionButton(props: ActionButtonProps) {
  const hidden = props.hidden ?? false;
  const isLoading = props.loading ?? false;
  const isDisabled = props.disabled || isLoading;

  if (hidden) return null;

  return (
    <Tooltip
      key={`tooltip-${props.tooltip ?? props.text}`}
      disabled={!props.tooltip && !props.text}
      label={props.tooltip ?? props.text}
      position={props.tooltipAlignment ?? 'left'}
    >
      <ActionIcon
        key={`action-icon-${props.tooltip ?? props.text}`}
        disabled={isDisabled}
        p={17}
        radius={props.radius ?? 'xs'}
        color={props.color}
        size={props.size}
        aria-label={`action-button-${identifierString(
          props.tooltip ?? props.text ?? ''
        )}`}
        onClick={(event: any) => {
          if (!isDisabled && props.onClick) {
            props.onClick(event);
          }
        }}
        // 🔄 loading color + subtle animation
        variant={isLoading ? 'light' : props.variant ?? 'transparent'}
        style={{
          opacity: isDisabled ? 0.6 : 1,
          cursor: isDisabled ? 'not-allowed' : 'pointer',
          transform: isLoading ? 'scale(0.97)' : 'scale(1)',
          transition: 'opacity 150ms ease, transform 150ms ease'
        }}
      >
        <Group gap="xs" wrap="nowrap">
          {isLoading ? <Loader size="xs" /> : props.icon}
        </Group>
      </ActionIcon>
    </Tooltip>
  );
}
