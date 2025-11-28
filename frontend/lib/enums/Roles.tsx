import { t } from '@lingui/core/macro';

/*
 * Enumeration of available user role groups
 */
export enum UserRoles {
  admin = 'admin',
  build = 'build',
  part = 'part',
  part_category = 'part_category',
  purchase_order = 'purchase_order',
  return_order = 'return_order',
  sales_order = 'sales_order',
  stock = 'stock',
  stock_location = 'stock_location',
  stocktake = 'stocktake',
  manufactured = 'manufactured', // 👈 NEW
  project = 'project',
  part_html_file = 'part_html_file',  // 👈 NEW: HTML file role
  bom_upload = 'bom_upload',  // 👈 NEW: BOM upload role

}

/*
 * Enumeration of available user permissions within each role group
 */
export enum UserPermissions {
  view = 'view',
  add = 'add',
  change = 'change',
  delete = 'delete'
}

export function userRoleLabel(role: UserRoles): string {
  switch (role) {
    case UserRoles.admin:
      return t`Admin`;
    case UserRoles.build:
      return t`Build Orders`;
    case UserRoles.part:
      return t`Parts`;
    case UserRoles.part_category:
      return t`Part Categories`;
    case UserRoles.manufactured:
      return t`Manufactured Parts`;
    case UserRoles.purchase_order:
      return t`Purchase Orders`;
    case UserRoles.return_order:
      return t`Return Orders`;
    case UserRoles.sales_order:
      return t`Sales Orders`;
    case UserRoles.stock:
      return t`Stock Items`;
    case UserRoles.stock_location:
      return t`Stock Location`;
    case UserRoles.stocktake:
      return t`Stocktake`;
    case UserRoles.project:
      return t`Projects`;
    case UserRoles.part_html_file:
      return t`Part HTML Files`;
    case UserRoles.bom_upload:
      return t`BOM Upload`;
    default:
      return role as string;
  }
}
