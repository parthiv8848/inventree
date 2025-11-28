import { t } from '@lingui/core/macro';
import { Stack } from '@mantine/core';
import { IconBuildingFactory2, IconBuildingWarehouse } from '@tabler/icons-react';
import { useMemo } from 'react';

import { UserRoles } from '@lib/enums/Roles';
import PermissionDenied from '../../components/errors/PermissionDenied';
import { PageDetail } from '../../components/nav/PageDetail';
import { PanelGroup } from '../../components/panels/PanelGroup';
import { useUserState } from '../../states/UserState';
import { CompanyTable } from '../../tables/company/CompanyTable';
import { ManufacturerPartTable } from '../../tables/purchasing/ManufacturerPartTable';

export default function ManufacturerIndex() {
  const user = useUserState();

  const panels = useMemo(() => {
    return [
      {
        name: 'manufacturers',
        label: t`Manufacturers`,
        icon: <IconBuildingFactory2 />,
        content: (
          <CompanyTable
            path='manufacturer'
            params={{ is_manufacturer: true }}
          />
        )
      },
    //   {
    //     name: 'manufacturer-parts',
    //     label: t`Manufacturer Parts`,
    //     icon: <IconBuildingWarehouse />,
    //     content: <ManufacturerPartTable params={{}} />
    //   }
    ];
  }, []);

  if (!user.isLoggedIn() || !user.hasViewRole(UserRoles.manufactured)) {
    return <PermissionDenied />;
  }

  return (
    <Stack>
      <PageDetail title={t`Manufacturers`} />
      <PanelGroup
        pageKey='manufacturer-index'
        panels={panels}
        model={'manufacturer'}
        id={null}
      />
    </Stack>
  );
}