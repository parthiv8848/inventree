import { t } from '@lingui/core/macro';
import {
  ActionIcon,
  Button,
  type MantineSize,
  Text,
  Tooltip
} from '@mantine/core';

import { InvenTreeIcon } from '../../functions/icons';
import { useState } from 'react';

import type { JSX } from 'react';

export function CopyButton({
  value,
  label,
  content,
  size
}: Readonly<{
  value: any;
  label?: string;
  content?: JSX.Element;
  size?: MantineSize;
}>) {
  const ButtonComponent = label ? Button : ActionIcon;
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    // console.log('Trying to copy:', value);

    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(value);
      } else {
        // fallback for insecure http://IP contexts
        const textarea = document.createElement('textarea');
        textarea.value = value;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
      }

      setCopied(true);
      // console.log('✅ Copy successful:', value);
      setTimeout(() => setCopied(false), 1500); // reset after 1.5s
    } catch (err) {
      // console.error('❌ Copy failed:', err);
    }
  };

  return (
    <Tooltip label={copied ? t`Copied` : t`Copy`} withArrow>
      <ButtonComponent
        color={copied ? 'teal' : 'gray'}
        onClick={handleCopy}
        variant="transparent"
        size={size ?? 'sm'}
      >
        {copied ? (
          <InvenTreeIcon icon="check" />
        ) : (
          <InvenTreeIcon icon="copy" />
        )}
        {content}
        {label && (
          <Text p={size ?? 'sm'} size={size ?? 'sm'}>
            {label}
          </Text>
        )}
      </ButtonComponent>
    </Tooltip>
  );
}


// import { t } from '@lingui/core/macro';
// import {
//   ActionIcon,
//   Button,
//   CopyButton as MantineCopyButton,
//   type MantineSize,
//   Text,
//   Tooltip
// } from '@mantine/core';

// import { InvenTreeIcon } from '../../functions/icons';

// import type { JSX } from 'react';

// export function CopyButton({
//   value,
//   label,
//   content,
//   size
// }: Readonly<{
//   value: any;
//   label?: string;
//   content?: JSX.Element;
//   size?: MantineSize;
// }>) {
//   const ButtonComponent = label ? Button : ActionIcon;

//   return (
//     <MantineCopyButton value={value}>
//       {({ copied, copy }) => (
//         <Tooltip label={copied ? t`Copied` : t`Copy`} withArrow>
//           <ButtonComponent
//             color={copied ? 'teal' : 'gray'}
//             onClick={copy}
//             variant='transparent'
//             size={size ?? 'sm'}
//           >
//             {copied ? (
//               <InvenTreeIcon icon='check' />
//             ) : (
//               <InvenTreeIcon icon='copy' />
//             )}
//             {content}
//             {label && (
//               <Text p={size ?? 'sm'} size={size ?? 'sm'}>
//                 {label}
//               </Text>
//             )}
//           </ButtonComponent>
//         </Tooltip>
//       )}
//     </MantineCopyButton>
//   );
// } 