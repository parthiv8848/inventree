"""JSON serializers for the Order API."""

from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models, transaction
from django.db.models import (
    BooleanField,
    Case,
    ExpressionWrapper,
    F,
    Prefetch,
    Q,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Greatest
from django.utils.translation import gettext_lazy as _

from rest_framework import serializers
from rest_framework.serializers import ValidationError
from sql_util.utils import SubqueryCount, SubquerySum

import build.serializers
import order.models
import part.filters as part_filters
import part.models as part_models
import stock.models
import stock.serializers
import stock.status_codes
from common.serializers import ProjectCodeSerializer
from company.serializers import (
    AddressBriefSerializer,
    CompanyBriefSerializer,
    ContactSerializer,
    SupplierPartSerializer,
)
from generic.states.fields import InvenTreeCustomStatusSerializerMixin
from importer.registry import register_importer
from InvenTree.helpers import (
    current_date,
    extract_serial_numbers,
    hash_barcode,
    normalize,
    str2bool,
)
from InvenTree.mixins import DataImportExportSerializerMixin
from InvenTree.ready import isGeneratingSchema
from InvenTree.serializers import (
    InvenTreeCurrencySerializer,
    InvenTreeDecimalField,
    InvenTreeModelSerializer,
    InvenTreeMoneySerializer,
    NotesFieldMixin,
)
from order.status_codes import (
    PurchaseOrderStatusGroups,
    ReturnOrderLineStatus,
    ReturnOrderStatus,
    SalesOrderStatusGroups,
)
from part.serializers import PartBriefSerializer
from stock.status_codes import StockStatus
from users.serializers import OwnerSerializer, UserSerializer


class TotalPriceMixin(serializers.Serializer):
    """Serializer mixin which provides total price fields."""

    total_price = InvenTreeMoneySerializer(allow_null=True, read_only=True)

    order_currency = InvenTreeCurrencySerializer(
        allow_blank=True,
        allow_null=True,
        required=False,
        label=_('Order Currency'),
        help_text=_('Currency for this order (leave blank to use company default)'),
    )


class DuplicateOrderSerializer(serializers.Serializer):
    """Serializer for specifying options when duplicating an order."""

    class Meta:
        """Metaclass options."""

        fields = ['order_id', 'copy_lines', 'copy_extra_lines']

    order_id = serializers.IntegerField(
        required=True, label=_('Order ID'), help_text=_('ID of the order to duplicate')
    )

    copy_lines = serializers.BooleanField(
        required=False,
        default=True,
        label=_('Copy Lines'),
        help_text=_('Copy line items from the original order'),
    )

    copy_extra_lines = serializers.BooleanField(
        required=False,
        default=True,
        label=_('Copy Extra Lines'),
        help_text=_('Copy extra line items from the original order'),
    )


class AbstractOrderSerializer(DataImportExportSerializerMixin, serializers.Serializer):
    """Abstract serializer class which provides fields common to all order types."""

    export_exclude_fields = ['notes', 'duplicate']

    import_exclude_fields = ['notes', 'duplicate']

    # Number of line items in this order
    line_items = serializers.IntegerField(
        read_only=True, allow_null=True, label=_('Line Items')
    )

    # Number of completed line items (this is an annotated field)
    completed_lines = serializers.IntegerField(
        read_only=True, allow_null=True, label=_('Completed Lines')
    )

    # Human-readable status text (read-only)
    status_text = serializers.CharField(source='get_status_display', read_only=True)

    # status field cannot be set directly
    status = serializers.IntegerField(read_only=True, label=_('Order Status'))

    # Reference string is *required*
    reference = serializers.CharField(required=True)

    # Detail for point-of-contact field
    contact_detail = ContactSerializer(
        source='contact', many=False, read_only=True, allow_null=True
    )

    # Detail for responsible field
    responsible_detail = OwnerSerializer(
        source='responsible', read_only=True, allow_null=True, many=False
    )

    project_code_label = serializers.CharField(
        source='project_code.code',
        read_only=True,
        label='Project Code Label',
        allow_null=True,
    )

    # Detail for project code field
    project_code_detail = ProjectCodeSerializer(
        source='project_code', read_only=True, many=False, allow_null=True
    )

    # Detail for address field
    address_detail = AddressBriefSerializer(
        source='address', many=False, read_only=True, allow_null=True
    )

    # Boolean field indicating if this order is overdue (Note: must be annotated)
    overdue = serializers.BooleanField(read_only=True, allow_null=True)

    barcode_hash = serializers.CharField(read_only=True)

    creation_date = serializers.DateField(
        required=False, allow_null=True, label=_('Creation Date')
    )

    created_by = UserSerializer(read_only=True)

    duplicate = DuplicateOrderSerializer(
        label=_('Duplicate Order'),
        help_text=_('Specify options for duplicating this order'),
        required=False,
        write_only=True,
    )

    def validate_reference(self, reference):
        """Custom validation for the reference field."""
        self.Meta.model.validate_reference_field(reference)
        return reference

    @staticmethod
    def annotate_queryset(queryset):
        """Add extra information to the queryset."""
        queryset = queryset.annotate(line_items=SubqueryCount('lines'))
        queryset = queryset.select_related('created_by')

        return queryset

    @staticmethod
    def order_fields(extra_fields):
        """Construct a set of fields for this serializer."""
        return [
            'pk',
            'created_by',
            'creation_date',
            'issue_date',
            'start_date',
            'target_date',
            'description',
            'line_items',
            'completed_lines',
            'link',
            'project_code',
            'project_code_label',
            'project_code_detail',
            'reference',
            'responsible',
            'responsible_detail',
            'contact',
            'contact_detail',
            'address',
            'address_detail',
            'status',
            'status_text',
            'status_custom_key',
            'notes',
            'barcode_hash',
            'overdue',
            'duplicate',
            *extra_fields,
        ]

    def clean_line_item(self, line):
        """Clean a line item object (when duplicating)."""
        line.pk = None
        line.order = self

    @transaction.atomic
    def create(self, validated_data):
        """Create a new order object.

        Optionally, copy line items from an existing order.
        """
        duplicate = validated_data.pop('duplicate', None)

        instance = super().create(validated_data)

        if duplicate:
            order_id = duplicate.get('order_id', None)
            copy_lines = duplicate.get('copy_lines', True)
            copy_extra_lines = duplicate.get('copy_extra_lines', True)

            try:
                copy_from = instance.__class__.objects.get(pk=order_id)
            except Exception:
                # If the order ID is invalid, raise a validation error
                raise ValidationError(_('Invalid order ID'))

            if copy_lines:
                for line in copy_from.lines.all():
                    instance.clean_line_item(line)
                    line.save()

            if copy_extra_lines:
                for line in copy_from.extra_lines.all():
                    line.pk = None
                    line.order = instance
                    line.save()

        return instance


class AbstractLineItemSerializer:
    """Abstract serializer for LineItem object."""

    target_date = serializers.DateField(
        required=False, allow_null=True, label=_('Target Date')
    )


class AbstractExtraLineSerializer(
    DataImportExportSerializerMixin, serializers.Serializer
):
    """Abstract Serializer for a ExtraLine object."""

    def __init__(self, *args, **kwargs):
        """Initialization routine for the serializer."""
        order_detail = kwargs.pop('order_detail', False)

        super().__init__(*args, **kwargs)

        if order_detail is not True and not isGeneratingSchema():
            self.fields.pop('order_detail', None)

    quantity = serializers.FloatField()

    price = InvenTreeMoneySerializer(allow_null=True)

    price_currency = InvenTreeCurrencySerializer()


class AbstractExtraLineMeta:
    """Abstract Meta for ExtraLine."""

    fields = [
        'pk',
        'description',
        'quantity',
        'reference',
        'notes',
        'context',
        'order',
        'order_detail',
        'price',
        'price_currency',
        'link',
    ]


@register_importer()
class PurchaseOrderSerializer(
    NotesFieldMixin,
    TotalPriceMixin,
    InvenTreeCustomStatusSerializerMixin,
    AbstractOrderSerializer,
    InvenTreeModelSerializer,
):
    """Serializer for a PurchaseOrder object."""

    class Meta:
        """Metaclass options."""

        model = order.models.PurchaseOrder

        fields = AbstractOrderSerializer.order_fields([
            'complete_date',
            'supplier',
            'supplier_detail',
            'supplier_reference',
            'supplier_name',
            'total_price',
            'order_currency',
            'destination',
            'shipping_charge',
            'bank_transfer_inr',  # New field
            'total_tax_inr',      # New field
            'exchange_rate',      # New field
            'received_date',   # ⭐ NEW

        ])

        read_only_fields = ['issue_date', 'complete_date', 'creation_date']

        extra_kwargs = {
            'supplier': {'required': True},
            'order_currency': {'required': False},
        }

    def __init__(self, *args, **kwargs):
        """Initialization routine for the serializer."""
        supplier_detail = kwargs.pop('supplier_detail', False)

        super().__init__(*args, **kwargs)

        if supplier_detail is not True and not isGeneratingSchema():
            self.fields.pop('supplier_detail', None)

    def skip_create_fields(self):
        """Skip these fields when instantiating a new object."""
        fields = super().skip_create_fields()

        return [*fields, 'duplicate']

    @staticmethod
    def annotate_queryset(queryset):
        """Add extra information to the queryset.

        - Number of lines in the PurchaseOrder
        - Overdue status of the PurchaseOrder
        """
        queryset = AbstractOrderSerializer.annotate_queryset(queryset)

        queryset = queryset.annotate(
            completed_lines=SubqueryCount(
                'lines', filter=Q(quantity__lte=F('received'))
            )
        )

        queryset = queryset.annotate(
            overdue=Case(
                When(
                    order.models.PurchaseOrder.overdue_filter(),
                    then=Value(True, output_field=BooleanField()),
                ),
                default=Value(False, output_field=BooleanField()),
            )
        )

        return queryset

    supplier_name = serializers.CharField(
        source='supplier.name', read_only=True, label=_('Supplier Name')
    )

    supplier_detail = CompanyBriefSerializer(
        source='supplier', many=False, read_only=True, allow_null=True
    )

class OrderAdjustSerializer(serializers.Serializer):
    """Generic serializer class for adjusting the status of an order."""

    class Meta:
        """Metaclass options.

        By default, there are no fields required for this serializer type.
        """

        fields = []

    @property
    def order(self):
        """Return the order object associated with this serializer.

        Note: It is passed in via the serializer context data.
        """
        return self.context['order']


class PurchaseOrderHoldSerializer(OrderAdjustSerializer):
    """Serializer for placing a PurchaseOrder on hold."""

    def save(self):
        """Save the serializer to 'hold' the order."""
        self.order.hold_order()


class PurchaseOrderCancelSerializer(OrderAdjustSerializer):
    """Serializer for cancelling a PurchaseOrder."""

    def save(self):
        """Save the serializer to 'cancel' the order."""
        if not self.order.can_cancel:
            raise ValidationError(_('Order cannot be cancelled'))

        self.order.cancel_order()


class PurchaseOrderCompleteSerializer(OrderAdjustSerializer):
    """Serializer for completing a purchase order."""

    class Meta:
        """Metaclass options."""

        fields = ['accept_incomplete']

    accept_incomplete = serializers.BooleanField(
        label=_('Accept Incomplete'),
        help_text=_('Allow order to be closed with incomplete line items'),
        required=False,
        default=False,
    )

    def validate_accept_incomplete(self, value):
        """Check if the 'accept_incomplete' field is required."""
        order = self.context['order']

        if not value and not order.is_complete:
            raise ValidationError(_('Order has incomplete line items'))

        return value

    def get_context_data(self):
        """Custom context information for this serializer."""
        order = self.context['order']

        return {'is_complete': order.is_complete}

    def save(self):
        """Save the serializer to 'complete' the order."""
        self.order.complete_order()


class PurchaseOrderIssueSerializer(OrderAdjustSerializer):
    """Serializer for issuing (sending) a purchase order."""

    def save(self):
        """Save the serializer to 'place' the order."""
        self.order.place_order()

        
@register_importer()
class PurchaseOrderLineItemSerializer(
    DataImportExportSerializerMixin,
    AbstractLineItemSerializer,
    InvenTreeModelSerializer,
):
    """Serializer class for the PurchaseOrderLineItem model with internal part upload support."""

    class Meta:
        """Metaclass options."""
        model = order.models.PurchaseOrderLineItem
        fields = [
            'pk',
            'part',
            'quantity',
            'reference',
            'notes',
            'order',
            'order_detail',
            'build_order',
            'build_order_detail',
            'overdue',
            'part_detail',
            'supplier_part_detail',
            'received',
            'purchase_price',
            'purchase_price_currency',
            'auto_pricing',
            'destination',
            'destination_detail',
            'target_date',
            'total_price',
            'link',
            'merge_items',
            'sku',
            'description',  # Added description field
            'mpn',
            'ipn',
            'internal_part',
            'internal_part_name',
            'case_and_package',
        ]

    def __init__(self, *args, **kwargs):
        """Initialization routine for the serializer."""
        part_detail = kwargs.pop('part_detail', False)
        order_detail = kwargs.pop('order_detail', False)
        
        super().__init__(*args, **kwargs)
        
        if isGeneratingSchema():
            return
            
        if part_detail is not True:
            self.fields.pop('part_detail', None)
            self.fields.pop('supplier_part_detail', None)
            
        if order_detail is not True:
            self.fields.pop('order_detail', None)

    def skip_create_fields(self):
        """Return a list of fields to skip when creating a new object."""
        return ['auto_pricing', 'merge_items', *super().skip_create_fields()]

    @staticmethod
    def annotate_queryset(queryset):
        """Add some extra annotations to this queryset.
        
        - "total_price" = purchase_price * quantity
        - "overdue" status (boolean field)
        """
        queryset = queryset.prefetch_related(
            Prefetch(
                'part__part',
                queryset=part_models.Part.objects.annotate(
                    category_default_location=part_filters.annotate_default_location(
                        'category__'
                    )
                ).prefetch_related(None),
            )
        )
        
        queryset = queryset.prefetch_related(
            'order',
            'order__responsible',
            'order__stock_items',
            'part__tags',
            'part__supplier',
            'part__manufacturer_part',
            'part__manufacturer_part__manufacturer',
            'part__part__pricing_data',
            'part__part__tags',
        )
        
        queryset = queryset.annotate(
            total_price=ExpressionWrapper(
                F('purchase_price') * F('quantity'),
                output_field=models.DecimalField()
            )
        )
        
        queryset = queryset.annotate(
            overdue=Case(
                When(
                    order.models.PurchaseOrderLineItem.OVERDUE_FILTER,
                    then=Value(True, output_field=BooleanField()),
                ),
                default=Value(False, output_field=BooleanField()),
            )
        )
        
        return queryset

    part = serializers.PrimaryKeyRelatedField(
        queryset=part_models.SupplierPart.objects.all(),
        many=False,
        required=False,  # Changed to False to allow internal part creation
        allow_null=True,
        label=_('Supplier Part'),
    )

    quantity = serializers.FloatField(min_value=0, required=True)

    def validate_quantity(self, quantity):
        """Validation for the 'quantity' field."""
        if quantity <= 0:
            raise ValidationError(_('Quantity must be greater than zero'))
        return quantity

    def validate_purchase_order(self, purchase_order):
        """Validation for the 'purchase_order' field."""
        if purchase_order.status not in PurchaseOrderStatusGroups.OPEN:
            raise ValidationError(_('Order is not open'))
        return purchase_order

    received = serializers.FloatField(default=0, read_only=True)
    overdue = serializers.BooleanField(read_only=True, allow_null=True)
    total_price = serializers.FloatField(read_only=True)
    
    part_detail = PartBriefSerializer(
        source='get_base_part', many=False, read_only=True, allow_null=True
    )
    
    supplier_part_detail = SupplierPartSerializer(
        source='part', brief=True, many=False, read_only=True, allow_null=True
    )
    
    purchase_price = InvenTreeMoneySerializer(allow_null=True)
    
    auto_pricing = serializers.BooleanField(
        label=_('Auto Pricing'),
        help_text=_(
            'Automatically calculate purchase price based on supplier part data'
        ),
        default=True,
    )
    
    destination_detail = stock.serializers.LocationBriefSerializer(
        source='get_destination', read_only=True, allow_null=True
    )
    
    purchase_price_currency = InvenTreeCurrencySerializer(
        help_text=_('Purchase price currency')
    )
    
    order_detail = PurchaseOrderSerializer(
        source='order', read_only=True, allow_null=True, many=False
    )
    
    build_order_detail = build.serializers.BuildSerializer(
        source='build_order', read_only=True, allow_null=True, many=False
    )
    
    merge_items = serializers.BooleanField(
        label=_('Merge Items'),
        help_text=_(
            'Merge items with the same part, destination and target date into one line item'
        ),
        default=True,
        write_only=True,
    )
    
    sku = serializers.CharField(
        allow_null=True, 
        required=False,
        label=_('SKU'),
        help_text=_('SKU from file upload, will be set on supplier part')
    )
    
    # Add description field to accept from file
    description = serializers.CharField(
        allow_null=True,
        required=False,
        allow_blank=True,
        label=_('Description'),
        help_text=_('Description from file upload')
    )
    
    sku = serializers.CharField(
        allow_null=True, 
        required=False,
        label=_('SKU'),
        help_text=_('SKU from file upload, will be set on supplier part')
    )
    
    mpn = serializers.CharField(
        source='part.manufacturer_part.MPN',
        read_only=True,
        allow_null=True,
        label=_('MPN'),
    )
    
    ipn = serializers.CharField(
        source='part.part.IPN',
        read_only=True,
        allow_null=True,
        label=_('Internal Part Number'),
    )

    # Changed to CharField to accept part name/IPN from file uploads
    internal_part = serializers.CharField(
        allow_null=True,
        required=True,
        write_only=True,  # Only for input, not output
        label=_('Internal Part'),
        help_text=_('Internal part name or IPN')
    )
    
    internal_part_name = serializers.CharField(
        source='part.part.name', read_only=True, label=_('Internal Part Name')
    )
 
    case_and_package = serializers.CharField(
        allow_blank=True,
        allow_null=True,
        required=False,
        label=_('Case / Package'),
        help_text=_('Case and package information'),
    )

    def get_internal_part_by_identifier(self, identifier):
        """
        Get internal part by name, IPN, or other identifier from uploaded file.
        """
        if not identifier:
            return None
            
        # Try to find part by various fields
        part = None
        
        # Try by IPN (Internal Part Number) first
        if not part:
            part = part_models.Part.objects.filter(IPN__iexact=identifier).first()
        
        # Try by name
        if not part:
            part = part_models.Part.objects.filter(name__iexact=identifier).first()
        
        # Try by name containing the identifier (partial match)
        if not part:
            part = part_models.Part.objects.filter(name__icontains=identifier).first()
        
        # Try by description
        if not part:
            part = part_models.Part.objects.filter(description__icontains=identifier).first()
        
        return part

    def get_or_create_supplier_part(self, internal_part, purchase_order, sku_from_file=None, description_from_file=None):
        """
        Get or create a supplier part for the given internal part and purchase order.
        This method handles cases where supplier part doesn't exist.
        
        Args:
            internal_part: The internal Part object
            purchase_order: The PurchaseOrder object
            sku_from_file: SKU from uploaded file (optional)
            description_from_file: Description from uploaded file (optional)
        """
        try:
            # Try to find existing supplier part for this internal part and supplier
            supplier_part = part_models.SupplierPart.objects.filter(
                part=internal_part,
                supplier=purchase_order.supplier
            ).first()
            
            if supplier_part:
                # Update existing supplier part with file data if provided
                updated = False
                
                if sku_from_file is not None:
                    supplier_part.SKU = sku_from_file
                    updated = True
                
                if description_from_file:
                    supplier_part.description = description_from_file
                    updated = True
                
                # Update manufacturer part if not already set and available from internal part
                if not supplier_part.manufacturer_part:
                    manufacturer_part = self.get_manufacturer_part_from_internal(internal_part)
                    if manufacturer_part:
                        supplier_part.manufacturer_part = manufacturer_part
                        updated = True
                
                if updated:
                    supplier_part.save()
                
                return supplier_part
            
            # Create new supplier part if it doesn't exist
            supplier_part_data = {
                'part': internal_part,
                'supplier': purchase_order.supplier,
            }
            
            # Set SKU from file or auto-generate if not provided
            if sku_from_file is not None:
                supplier_part_data['SKU'] = sku_from_file
            else:
                # Auto-generate SKU if not provided in file
                auto_sku = f"AUTO-{internal_part.IPN or internal_part.name or internal_part.pk}"
                supplier_part_data['SKU'] = auto_sku
            
            # Set description from file if provided
            if description_from_file:
                supplier_part_data['description'] = description_from_file
            
            # Get manufacturer and MPN from internal part's manufacturer parts
            manufacturer_part = self.get_manufacturer_part_from_internal(internal_part)
            if manufacturer_part:
                supplier_part_data['manufacturer_part'] = manufacturer_part
            
            supplier_part = part_models.SupplierPart.objects.create(**supplier_part_data)
            
            return supplier_part
            
        except Exception as e:
            raise ValidationError({
                'internal_part': f'Error creating supplier part: {str(e)}'
            })

    def get_manufacturer_part_from_internal(self, internal_part):
        """
        Get manufacturer part from internal part.
        Looks for manufacturer parts associated with the internal part.
        """
        try:
            # First try to get manufacturer part directly from the part
            if hasattr(internal_part, 'manufacturer_parts'):
                manufacturer_part = internal_part.manufacturer_parts.first()
                if manufacturer_part:
                    return manufacturer_part
            
            # Alternative: try to get from manufacturer_part relationship if it exists
            if hasattr(internal_part, 'manufacturer_part') and internal_part.manufacturer_part:
                return internal_part.manufacturer_part
                
            # If no manufacturer part found, try to create one if part has MPN
            if hasattr(internal_part, 'MPN') and internal_part.MPN:
                # Try to find existing manufacturer part by MPN
                manufacturer_part = part_models.ManufacturerPart.objects.filter(
                    MPN=internal_part.MPN
                ).first()
                if manufacturer_part:
                    return manufacturer_part
            
            return None
            
        except Exception:
            return None

    def validate(self, data):
        """Custom validation for the serializer.
        
        Modified to support internal part-based uploads:
        - If internal_part identifier is provided, lookup the actual part object
        - If internal_part is found but part (supplier_part) is not, create supplier part
        - Handle SKU and description from file
        - Ensure purchase_order is supplied
        - Remove supplier matching validation for internal part uploads
        """
        data = super().validate(data)
        
        supplier_part = data.get('part', None)
        internal_part_identifier = data.get('internal_part', None)
        purchase_order = data.get('order', None)
        sku_from_file = data.get('sku', None)
        description_from_file = data.get('description', None)

        if not purchase_order:
            raise ValidationError({'order': _('Purchase order must be specified')})

        # Handle internal part lookup from identifier (name/IPN from file)
        internal_part_obj = None
        if internal_part_identifier:
            internal_part_obj = self.get_internal_part_by_identifier(internal_part_identifier)
            
            if not internal_part_obj:
                raise ValidationError({
                    'internal_part': f'Internal part "{internal_part_identifier}" not found. '
                                   'Please check the part name or IPN exists in the system.'
                })

        # Handle internal part upload logic
        if internal_part_obj and not supplier_part:
            # Create or get supplier part based on internal part with file data
            supplier_part = self.get_or_create_supplier_part(
                internal_part_obj, 
                purchase_order,
                sku_from_file=sku_from_file,
                description_from_file=description_from_file
            )
            data['part'] = supplier_part
            
        elif not supplier_part and not internal_part_obj:
            raise ValidationError({
                'part': _('Either supplier part or internal part must be specified')
            })

        # Remove the processed fields from data as they're handled in supplier part creation
        fields_to_remove = ['internal_part', 'sku', 'description']
        for field in fields_to_remove:
            if field in data:
                del data[field]
        
        return data

    def create(self, validated_data):
        """Custom create method to handle internal part uploads."""
        # internal_part identifier is already removed in validate() method
        # The supplier part should already be set in validate() method
        return super().create(validated_data)

    def update(self, instance, validated_data):
        """Custom update method to handle internal part updates."""
        # internal_part identifier is already processed in validate() method
        return super().update(instance, validated_data)


@register_importer()
class PurchaseOrderExtraLineSerializer(
    AbstractExtraLineSerializer, InvenTreeModelSerializer
):
    """Serializer for a PurchaseOrderExtraLine object."""

    order_detail = PurchaseOrderSerializer(
        source='order', many=False, read_only=True, allow_null=True
    )

    class Meta(AbstractExtraLineMeta):
        """Metaclass options."""

        model = order.models.PurchaseOrderExtraLine


class PurchaseOrderLineItemReceiveSerializer(serializers.Serializer):
    """A serializer for receiving a single purchase order line item against a purchase order."""

    class Meta:
        """Metaclass options."""

        fields = [
            'barcode',
            'line_item',
            'location',
            'quantity',
            'status',
            'batch_code',
            'expiry_date',
            'serial_numbers',
            'packaging',
            'note',
        ]

    line_item = serializers.PrimaryKeyRelatedField(
        queryset=order.models.PurchaseOrderLineItem.objects.all(),
        many=False,
        allow_null=False,
        required=True,
        label=_('Line Item'),
    )

    def validate_line_item(self, item):
        """Validation for the 'line_item' field."""
        if item.order != self.context['order']:
            raise ValidationError(_('Line item does not match purchase order'))

        return item

    location = serializers.PrimaryKeyRelatedField(
        queryset=stock.models.StockLocation.objects.all(),
        many=False,
        allow_null=True,
        required=False,
        label=_('Location'),
        help_text=_('Select destination location for received items'),
    )

    quantity = serializers.DecimalField(
        max_digits=15, decimal_places=5, min_value=Decimal(0), required=True
    )

    def validate_quantity(self, quantity):
        """Validation for the 'quantity' field."""
        if quantity <= 0:
            raise ValidationError(_('Quantity must be greater than zero'))

        return quantity

    batch_code = serializers.CharField(
        label=_('Batch Code'),
        help_text=_('Enter batch code for incoming stock items'),
        required=False,
        default='',
        allow_blank=True,
    )

    expiry_date = serializers.DateField(
        label=_('Expiry Date'),
        help_text=_('Enter expiry date for incoming stock items'),
        required=False,
        allow_null=True,
        default=None,
    )

    serial_numbers = serializers.CharField(
        label=_('Serial Numbers'),
        help_text=_('Enter serial numbers for incoming stock items'),
        required=False,
        default='',
        allow_blank=True,
    )

    status = stock.serializers.StockStatusCustomSerializer(default=StockStatus.OK.value)

    packaging = serializers.CharField(
        label=_('Packaging'),
        help_text=_('Override packaging information for incoming stock items'),
        required=False,
        default='',
        allow_blank=True,
    )

    note = serializers.CharField(
        label=_('Note'),
        help_text=_('Additional note for incoming stock items'),
        required=False,
        default='',
        allow_blank=True,
    )

    barcode = serializers.CharField(
        label=_('Barcode'),
        help_text=_('Scanned barcode'),
        default='',
        required=False,
        allow_null=True,
        allow_blank=True,
    )

    def validate_barcode(self, barcode):
        """Cannot check in a LineItem with a barcode that is already assigned."""
        # Ignore empty barcode values
        if not barcode or barcode.strip() == '':
            return None

        barcode_hash = hash_barcode(barcode)

        if stock.models.StockItem.lookup_barcode(barcode_hash) is not None:
            raise ValidationError(_('Barcode is already in use'))

        return barcode

    def validate(self, data):
        """Custom validation for the serializer.

        - Integer quantity must be provided for serialized stock
        - Validate serial numbers (if provided)
        """
        data = super().validate(data)

        line_item = data['line_item']
        quantity = data['quantity']
        serial_numbers = data.get('serial_numbers', '').strip()

        base_part = line_item.part.part
        base_quantity = line_item.part.base_quantity(quantity)

        # Does the quantity need to be "integer" (for trackable parts?)
        if base_part.trackable and Decimal(base_quantity) != int(base_quantity):
            raise ValidationError({
                'quantity': _(
                    'An integer quantity must be provided for trackable parts'
                )
            })

        # If serial numbers are provided
        if serial_numbers:
            try:
                # Pass the serial numbers through to the parent serializer once validated
                data['serials'] = extract_serial_numbers(
                    serial_numbers,
                    base_quantity,
                    base_part.get_latest_serial_number(),
                    part=base_part,
                )
            except DjangoValidationError as e:
                raise ValidationError({'serial_numbers': e.messages})

            invalid_serials = []

            # Check the serial numbers are valid
            for serial in data['serials']:
                try:
                    base_part.validate_serial_number(serial, raise_error=True)
                except (ValidationError, DjangoValidationError):
                    invalid_serials.append(serial)

            if len(invalid_serials) > 0:
                msg = _('The following serial numbers already exist or are invalid')
                msg += ': ' + ', '.join(invalid_serials)
                raise ValidationError({'serial_numbers': msg})

        return data


class PurchaseOrderReceiveSerializer(serializers.Serializer):
    """Serializer for receiving items against a PurchaseOrder."""

    class Meta:
        """Metaclass options."""

        fields = ['items', 'location']

    items = PurchaseOrderLineItemReceiveSerializer(many=True)

    location = serializers.PrimaryKeyRelatedField(
        queryset=stock.models.StockLocation.objects.all(),
        many=False,
        required=False,
        allow_null=True,
        label=_('Location'),
        help_text=_('Select destination location for received items'),
    )

    def validate(self, data):
        """Custom validation for the serializer.

        - Ensure line items are provided
        - Check that a location is specified
        """
        super().validate(data)

        order = self.context['order']
        items = data.get('items', [])

        location = data.get('location', order.destination)

        if len(items) == 0:
            raise ValidationError(_('Line items must be provided'))

        # Check if the location is not specified for any particular item
        for item in items:
            line = item['line_item']

            if not item.get('location', None):
                # If a global location is specified, use that
                item['location'] = location

            if not item['location']:
                # The line item specifies a location?
                item['location'] = line.get_destination()

            if not item['location']:
                raise ValidationError({
                    'location': _('Destination location must be specified')
                })

        # Ensure barcodes are unique
        unique_barcodes = set()

        for item in items:
            barcode = item.get('barcode', '')

            if barcode:
                if barcode in unique_barcodes:
                    raise ValidationError(_('Supplied barcode values must be unique'))
                else:
                    unique_barcodes.add(barcode)

        return data

    def save(self):
        """Perform the actual database transaction to receive purchase order items."""
        data = self.validated_data

        request = self.context.get('request')
        order = self.context['order']

        items = data['items']

        # Location can be provided, or default to the order destination
        location = data.get('location', order.destination)

        # Now we can actually receive the items into stock
        with transaction.atomic():
            for item in items:
                # Select location (in descending order of priority)
                loc = (
                    item.get('location', None)
                    or location
                    or item['line_item'].get_destination()
                )

                try:
                    order.receive_line_item(
                        item['line_item'],
                        loc,
                        item['quantity'],
                        request.user if request else None,
                        status=item['status'],
                        barcode=item.get('barcode', ''),
                        batch_code=item.get('batch_code', ''),
                        expiry_date=item.get('expiry_date', None),
                        packaging=item.get('packaging', ''),
                        serials=item.get('serials', None),
                        notes=item.get('note', None),
                    )
                except (ValidationError, DjangoValidationError) as exc:
                    # Catch model errors and re-throw as DRF errors
                    raise ValidationError(detail=serializers.as_serializer_error(exc))
from rest_framework import serializers
from .models import CourierCompany ,Company # Adjust the import based on your project structure

class CourierCompanySerializer(serializers.ModelSerializer):
    """Serializer for the CourierCompany model."""

    pk = serializers.IntegerField(source='id', read_only=True)

    class Meta:
        model = CourierCompany
        fields = ['pk', 'company_name', 'website', 'tracking_link']  # Expose 'pk' instead of 'id'

@register_importer()
class SalesOrderSerializer(
    NotesFieldMixin,
    TotalPriceMixin,
    InvenTreeCustomStatusSerializerMixin,
    AbstractOrderSerializer,
    InvenTreeModelSerializer,
):
    """Serializer for the SalesOrder model class."""

    country = serializers.ChoiceField(
        choices=[('India', 'India'), ('International', 'International')],
        required=False,
        help_text=_('Country of the customer')
    )

    gst_number = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text=_('GST number (required if the country is India)')
    )

    # -------- NEW: link returned by SalesOrder.get_shipping_label_url() -----
    shipping_label_url = serializers.SerializerMethodField()

    # -------- NEW: expose send_shipment from latest shipment -----
    send_shipment = serializers.SerializerMethodField()

    def get_shipping_label_url(self, obj):
        return obj.get_shipping_label_url(self.context.get("request"))

    def get_send_shipment(self, obj):
        """Return send_shipment flag from the latest shipment."""
        latest_shipment = obj.shipments.order_by('-shipment_date').first()
        return latest_shipment.send_shipment if latest_shipment else None

    class Meta:
        """Metaclass options."""

        model = order.models.SalesOrder

        fields = AbstractOrderSerializer.order_fields([
            'customer',
            'customer_detail',
            'customer_reference',
            'shipment_date',
            'total_price',
            'order_currency',
            'shipments_count',
            'completed_shipments_count',
            'country',
            'gst_number',
            'shipping_label_url',
            'wordpress_order_id',
            'send_shipment',   # 👈 Add the new field
            'batch',  # <-- add here
        ])

        read_only_fields = [
            'status',
            'creation_date',
            'shipment_date',
            'shipping_label_url',
            'send_shipment',   # 👈 mark as read-only
        ]

        extra_kwargs = {'order_currency': {'required': False}}

    def __init__(self, *args, **kwargs):
        """Initialization routine for the serializer."""
        customer_detail = kwargs.pop('customer_detail', False)

        super().__init__(*args, **kwargs)

        if customer_detail is not True and not isGeneratingSchema():
            self.fields.pop('customer_detail', None)

    def skip_create_fields(self):
        """Skip these fields when instantiating a new object."""
        fields = super().skip_create_fields()

        return [*fields, 'duplicate']

    @staticmethod
    def annotate_queryset(queryset):
        """Add extra information to the queryset.

        - Number of line items in the SalesOrder
        - Number of completed line items in the SalesOrder
        - Overdue status of the SalesOrder
        """
        queryset = AbstractOrderSerializer.annotate_queryset(queryset)

        queryset = queryset.annotate(
            completed_lines=SubqueryCount('lines', filter=Q(quantity__lte=F('shipped')))
        )

        queryset = queryset.annotate(
            overdue=Case(
                When(
                    order.models.SalesOrder.overdue_filter(),
                    then=Value(True, output_field=BooleanField()),
                ),
                default=Value(False, output_field=BooleanField()),
            )
        )

        # Annotate shipment details
        queryset = queryset.annotate(
            shipments_count=SubqueryCount('shipments'),
            completed_shipments_count=SubqueryCount(
                'shipments', filter=Q(shipment_date__isnull=False)
            ),
        )

        return queryset

    customer_detail = CompanyBriefSerializer(
        source='customer', many=False, read_only=True, allow_null=True
    )

    shipments_count = serializers.IntegerField(
        read_only=True, allow_null=True, label=_('Shipments')
    )

    completed_shipments_count = serializers.IntegerField(
        read_only=True, allow_null=True, label=_('Completed Shipments')
    )
    def create(self, validated_data):
        from order.api import create_zoho_invoice_fun  # 👈 LOCAL IMPORT

        print("Creating SalesOrder with data:", validated_data)

        # Get the customer instance directly
        customer = validated_data.get('customer')
        
        # Initialize country and GST number variables
        country = validated_data.get('country', 'International')  # Default to 'International' if not provided
        gst_number = validated_data.get('gst_number', '')  # Default to an empty string if not provided

        if customer:
            company_instance = Company.objects.filter(id=customer.id).first()
            
            if company_instance:
                # Set the country based on the company instance if user hasn't provided one
                if not country:
                    country = company_instance.country
                
                # Only set GST number if the country is India
                if country == 'India':
                    if not gst_number:  # If GST number is not provided by user
                        gst_number = company_instance.gst_number or ''
                    validated_data['gst_number'] = gst_number
                
                # Clear GST number if the country is not India
                if country != 'India':
                    validated_data['gst_number'] = ''

                validated_data['country'] = country
            else:
                # If no company instance, allow user input for country and GST number
                validated_data['country'] = country
                if country == 'India' and not gst_number:
                    raise serializers.ValidationError({'gst_number': 'GST number is required for Indian customers.'})
                elif country != 'India':
                    validated_data['gst_number'] = ''  # Set GST number to an empty string for International

        # Call the parent create method
        order = super().create(validated_data)
        print("SalesOrder created successfully:", order)
        print("Created SalesOrder ID:", order.id)
        
        # Create a Zoho invoice
        # try:
        #     create_zoho_invoice_fun(order.id) 
        # except Exception as e:
        #     print(f"Error creating Zoho invoice: {e}")
        #     raise serializers.ValidationError({'zoho_invoice': 'Failed to create Zoho invoice.'})
        # print("Zoho invoice created successfully for SalesOrder ID:", order.id)
        
        return order


    def update(self, instance, validated_data):
        print("Updating SalesOrder with data:", validated_data)

        # Check and update country and GST number if customer is provided
        customer = validated_data.get('customer', instance.customer)

        # Initialize country and GST number variables
        country = validated_data.get('country', instance.country)  # Use the provided or current instance value
        gst_number = validated_data.get('gst_number', instance.gst_number)  # Use the provided or current instance value

        if customer:
            company_instance = Company.objects.filter(id=customer.id).first()
            
            if company_instance:
                # Update the country based on the company instance if user hasn't provided one
                if not country:
                    country = company_instance.country

                # Only set GST number if the country is India
                if country == 'India':
                    if not gst_number:  # If GST number is not provided by user
                        gst_number = company_instance.gst_number or ''
                    instance.gst_number = gst_number
                else:
                    # Clear GST number if the country is not India
                    instance.gst_number = ''

                instance.country = country
            else:
                # If no company instance, allow user input for country and GST number
                instance.country = country
                if country == 'India':
                    if not gst_number:
                        raise serializers.ValidationError({'gst_number': 'GST number is required for Indian customers.'})
                    instance.gst_number = gst_number  # Set provided GST number if country is India
                else:
                    instance.gst_number = ''  # Set GST number to an empty string for International customers

        # Call the parent update method
        return super().update(instance, validated_data)


class SalesOrderIssueSerializer(OrderAdjustSerializer):
    """Serializer for issuing a SalesOrder."""

    def save(self):
        """Save the serializer to 'issue' the order."""
        self.order.issue_order()


@register_importer()
class SalesOrderLineItemSerializer(
    DataImportExportSerializerMixin,
    AbstractLineItemSerializer,
    InvenTreeModelSerializer,
):
    """Serializer for a SalesOrderLineItem object."""

    class Meta:
        """Metaclass options."""

        model = order.models.SalesOrderLineItem

        fields = [
            'pk',
            'allocated',
            'customer_detail',
            'quantity',
            'reference',
            'notes',
            'order',
            'order_detail',
            'overdue',
            'part',
            'part_detail',
            'sale_price',
            'sale_price_currency',
            'shipped',
            'target_date',
            'link',
            # Annotated fields for part stocking information
            'available_stock',
            'available_variant_stock',
            'building',
            'on_order',
        ]

    def __init__(self, *args, **kwargs):
        """Initialization routine for the serializer.

        - Add extra related serializer information if required
        """
        part_detail = kwargs.pop('part_detail', False)
        order_detail = kwargs.pop('order_detail', False)
        customer_detail = kwargs.pop('customer_detail', False)

        super().__init__(*args, **kwargs)

        if isGeneratingSchema():
            return

        if part_detail is not True:
            self.fields.pop('part_detail', None)

        if order_detail is not True:
            self.fields.pop('order_detail', None)

        if customer_detail is not True:
            self.fields.pop('customer_detail', None)

    @staticmethod
    def annotate_queryset(queryset):
        """Add some extra annotations to this queryset.

        - "overdue" status (boolean field)
        - "available_quantity"
        - "building"
        - "on_order"
        """
        queryset = queryset.annotate(
            overdue=Case(
                When(
                    Q(order__status__in=SalesOrderStatusGroups.OPEN)
                    & order.models.SalesOrderLineItem.OVERDUE_FILTER,
                    then=Value(True, output_field=BooleanField()),
                ),
                default=Value(False, output_field=BooleanField()),
            )
        )

        # Annotate each line with the available stock quantity
        # To do this, we need to look at the total stock and any allocations
        queryset = queryset.alias(
            total_stock=part_filters.annotate_total_stock(reference='part__'),
            allocated_to_sales_orders=part_filters.annotate_sales_order_allocations(
                reference='part__'
            ),
            allocated_to_build_orders=part_filters.annotate_build_order_allocations(
                reference='part__'
            ),
        )

        queryset = queryset.annotate(
            available_stock=Greatest(
                ExpressionWrapper(
                    F('total_stock')
                    - F('allocated_to_sales_orders')
                    - F('allocated_to_build_orders'),
                    output_field=models.DecimalField(),
                ),
                0,
                output_field=models.DecimalField(),
            )
        )

        # Filter for "variant" stock: Variant stock items must be salable and active
        variant_stock_query = part_filters.variant_stock_query(
            reference='part__'
        ).filter(part__salable=True, part__active=True)

        # Also add in available "variant" stock
        queryset = queryset.alias(
            variant_stock_total=part_filters.annotate_variant_quantity(
                variant_stock_query, reference='quantity'
            ),
            variant_bo_allocations=part_filters.annotate_variant_quantity(
                variant_stock_query, reference='sales_order_allocations__quantity'
            ),
            variant_so_allocations=part_filters.annotate_variant_quantity(
                variant_stock_query, reference='allocations__quantity'
            ),
        )

        queryset = queryset.annotate(
            available_variant_stock=Greatest(
                ExpressionWrapper(
                    F('variant_stock_total')
                    - F('variant_bo_allocations')
                    - F('variant_so_allocations'),
                    output_field=models.DecimalField(),
                ),
                0,
                output_field=models.DecimalField(),
            )
        )

        # Add information about the quantity of parts currently on order
        queryset = queryset.annotate(
            on_order=part_filters.annotate_on_order_quantity(reference='part__')
        )

        # Add information about the quantity of parts currently in production
        queryset = queryset.annotate(
            building=part_filters.annotate_in_production_quantity(reference='part__')
        )

        # Annotate total 'allocated' stock quantity
        queryset = queryset.annotate(
            allocated=Coalesce(
                SubquerySum('allocations__quantity'),
                Decimal(0),
                output_field=models.DecimalField(),
            )
        )

        return queryset

    order_detail = SalesOrderSerializer(
        source='order', many=False, read_only=True, allow_null=True
    )
    part_detail = PartBriefSerializer(
        source='part', many=False, read_only=True, allow_null=True
    )
    customer_detail = CompanyBriefSerializer(
        source='order.customer', many=False, read_only=True, allow_null=True
    )

    # Annotated fields
    overdue = serializers.BooleanField(read_only=True, allow_null=True)
    available_stock = serializers.FloatField(read_only=True)
    available_variant_stock = serializers.FloatField(read_only=True)
    on_order = serializers.FloatField(label=_('On Order'), read_only=True)
    building = serializers.FloatField(label=_('In Production'), read_only=True)

    quantity = InvenTreeDecimalField()

    allocated = serializers.FloatField(read_only=True)

    shipped = InvenTreeDecimalField(read_only=True)

    sale_price = InvenTreeMoneySerializer(allow_null=True)

    sale_price_currency = InvenTreeCurrencySerializer(
        help_text=_('Sale price currency')
    )

from order.models import SalesOrderShipment  # Correct the path to your models if needed
@register_importer()
class SalesOrderShipmentSerializer(NotesFieldMixin, InvenTreeModelSerializer):
    """Serializer for the SalesOrderShipment class."""
    courier_company = serializers.PrimaryKeyRelatedField(
        queryset=CourierCompany.objects.all(),
        required=False,
        allow_null=True
    )

    courier_company_detail = CourierCompanySerializer(
        source='courier_company',
        read_only=True
    )
    class Meta:
        """Metaclass options."""

        model = order.models.SalesOrderShipment

        fields = [
            'pk',
            'order',
            'order_detail',
            'allocated_items',
            'shipment_date',
            'delivery_date',
            'checked_by',
            'reference',
            'tracking_number',
            'awb_number',
            'invoice_number',
            'barcode_hash',
            'link',
            'notes',
            'courier_company',          # Write-only field for setting the courier company by ID
            'courier_company_detail',
            'send_shipment'  # Read-only detailed view of the courier company
        ]

    def __init__(self, *args, **kwargs):
        """Initialization routine for the serializer."""
        order_detail = kwargs.pop('order_detail', True)

        super().__init__(*args, **kwargs)

        if not order_detail and not isGeneratingSchema():
            self.fields.pop('order_detail', None)

    @staticmethod
    def annotate_queryset(queryset):
        """Annotate the queryset with extra information."""
        # Prefetch related objects
        queryset = queryset.prefetch_related('order', 'order__customer', 'allocations')

        queryset = queryset.annotate(allocated_items=SubqueryCount('allocations'))

        return queryset

    allocated_items = serializers.IntegerField(
        read_only=True, allow_null=True, label=_('Allocated Items')
    )

    order_detail = SalesOrderSerializer(
        source='order', read_only=True, allow_null=True, many=False
    )


class SalesOrderAllocationSerializer(InvenTreeModelSerializer):
    """Serializer for the SalesOrderAllocation model.

    This includes some fields from the related model objects.
    """

    class Meta:
        """Metaclass options."""

        model = order.models.SalesOrderAllocation

        fields = [
            'pk',
            'item',
            'quantity',
            'shipment',
            # Annotated read-only fields
            'line',
            'part',
            'order',
            'serial',
            'location',
            # Extra detail fields
            'item_detail',
            'part_detail',
            'order_detail',
            'customer_detail',
            'location_detail',
            'shipment_detail',
        ]

        read_only_fields = ['line', '']

    def __init__(self, *args, **kwargs):
        """Initialization routine for the serializer."""
        order_detail = kwargs.pop('order_detail', False)
        part_detail = kwargs.pop('part_detail', True)
        item_detail = kwargs.pop('item_detail', True)
        location_detail = kwargs.pop('location_detail', False)
        customer_detail = kwargs.pop('customer_detail', False)

        super().__init__(*args, **kwargs)

        if isGeneratingSchema():
            return

        if not order_detail:
            self.fields.pop('order_detail', None)

        if not part_detail:
            self.fields.pop('part_detail', None)

        if not item_detail:
            self.fields.pop('item_detail', None)

        if not location_detail:
            self.fields.pop('location_detail', None)

        if not customer_detail:
            self.fields.pop('customer_detail', None)

    part = serializers.PrimaryKeyRelatedField(source='item.part', read_only=True)
    order = serializers.PrimaryKeyRelatedField(
        source='line.order', many=False, read_only=True
    )
    serial = serializers.CharField(source='get_serial', read_only=True, allow_null=True)
    quantity = serializers.FloatField(read_only=False)
    location = serializers.PrimaryKeyRelatedField(
        source='item.location', many=False, read_only=True
    )

    # Extra detail fields
    order_detail = SalesOrderSerializer(
        source='line.order', many=False, read_only=True, allow_null=True
    )
    part_detail = PartBriefSerializer(
        source='item.part', many=False, read_only=True, allow_null=True
    )
    item_detail = stock.serializers.StockItemSerializer(
        source='item',
        many=False,
        read_only=True,
        allow_null=True,
        part_detail=False,
        location_detail=False,
        supplier_part_detail=False,
    )
    location_detail = stock.serializers.LocationBriefSerializer(
        source='item.location', many=False, read_only=True, allow_null=True
    )
    customer_detail = CompanyBriefSerializer(
        source='line.order.customer', many=False, read_only=True, allow_null=True
    )

    shipment_detail = SalesOrderShipmentSerializer(
        source='shipment', order_detail=False, many=False, read_only=True
    )


class SalesOrderShipmentCompleteSerializer(serializers.ModelSerializer):
    """Serializer for completing (shipping) a SalesOrderShipment."""

    class Meta:
        """Metaclass options."""

        model = order.models.SalesOrderShipment

        fields = [
            'shipment_date',
            'delivery_date',
            'tracking_number',
            'invoice_number',
            'link',
        ]

    def validate(self, data):
        """Custom validation for the serializer.

        - Ensure the shipment reference is provided
        """
        data = super().validate(data)

        shipment = self.context.get('shipment', None)

        if not shipment:
            raise ValidationError(_('No shipment details provided'))

        shipment.check_can_complete(raise_error=True)

        return data

    def save(self):
        """Save the serializer to complete the SalesOrderShipment."""
        shipment = self.context.get('shipment', None)

        if not shipment:
            return

        data = self.validated_data

        request = self.context.get('request')
        user = request.user if request else None

        # Extract shipping date (defaults to today's date)
        now = current_date()
        shipment_date = data.get('shipment_date', now)
        if shipment_date is None:
            # Shipment date should not be None - check above only
            # checks if shipment_date exists in data
            shipment_date = now

        shipment.complete_shipment(
            user,
            tracking_number=data.get('tracking_number', shipment.tracking_number),
            invoice_number=data.get('invoice_number', shipment.invoice_number),
            link=data.get('link', shipment.link),
            shipment_date=shipment_date,
            delivery_date=data.get('delivery_date', shipment.delivery_date),
        )


class SalesOrderShipmentAllocationItemSerializer(serializers.Serializer):
    """A serializer for allocating a single stock-item against a SalesOrder shipment."""

    class Meta:
        """Metaclass options."""

        fields = ['line_item', 'stock_item', 'quantity']

    line_item = serializers.PrimaryKeyRelatedField(
        queryset=order.models.SalesOrderLineItem.objects.all(),
        many=False,
        allow_null=False,
        required=True,
        label=_('Stock Item'),
    )

    def validate_line_item(self, line_item):
        """Custom validation for the 'line_item' field.

        - Ensure the line_item is associated with the particular SalesOrder
        """
        order = self.context['order']

        # Ensure that the line item points to the correct order
        if line_item.order != order:
            raise ValidationError(_('Line item is not associated with this order'))

        return line_item

    stock_item = serializers.PrimaryKeyRelatedField(
        queryset=stock.models.StockItem.objects.all(),
        many=False,
        allow_null=False,
        required=True,
        label=_('Stock Item'),
    )

    quantity = serializers.DecimalField(
        max_digits=15, decimal_places=5, min_value=Decimal(0), required=True
    )

    def validate_quantity(self, quantity):
        """Custom validation for the 'quantity' field."""
        if quantity <= 0:
            raise ValidationError(_('Quantity must be positive'))

        return quantity

    def validate(self, data):
        """Custom validation for the serializer.

        - Ensure that the quantity is 1 for serialized stock
        - Quantity cannot exceed the available amount
        """
        data = super().validate(data)

        stock_item = data['stock_item']
        quantity = data['quantity']

        if stock_item.serialized and quantity != 1:
            raise ValidationError({
                'quantity': _('Quantity must be 1 for serialized stock item')
            })

        q = normalize(stock_item.unallocated_quantity())

        if quantity > q:
            raise ValidationError({'quantity': _(f'Available quantity ({q}) exceeded')})

        return data


class SalesOrderCompleteSerializer(OrderAdjustSerializer):
    """DRF serializer for manually marking a sales order as complete."""

    class Meta:
        """Serializer metaclass options."""

        fields = ['accept_incomplete']

    accept_incomplete = serializers.BooleanField(
        label=_('Accept Incomplete'),
        help_text=_('Allow order to be closed with incomplete line items'),
        required=False,
        default=False,
    )

    def validate_accept_incomplete(self, value):
        """Check if the 'accept_incomplete' field is required."""
        order = self.context['order']

        if not value and not order.is_completed():
            raise ValidationError(_('Order has incomplete line items'))

        return value

    def get_context_data(self):
        """Custom context data for this serializer."""
        order = self.context['order']

        return {
            'is_complete': order.is_completed(),
            'pending_shipments': order.pending_shipment_count,
        }

    def validate(self, data):
        """Custom validation for the serializer."""
        data = super().validate(data)
        self.order.can_complete(
            raise_error=True,
            allow_incomplete_lines=str2bool(data.get('accept_incomplete', False)),
        )

        return data

    def save(self):
        """Save the serializer to complete the SalesOrder."""
        request = self.context.get('request')
        data = self.validated_data

        user = request.user if request else None

        self.order.ship_order(
            user, allow_incomplete_lines=str2bool(data.get('accept_incomplete', False))
        )


class SalesOrderHoldSerializer(OrderAdjustSerializer):
    """Serializer for placing a SalesOrder on hold."""

    def save(self):
        """Save the serializer to place the SalesOrder on hold."""
        self.order.hold_order()


class SalesOrderCancelSerializer(OrderAdjustSerializer):
    """Serializer for marking a SalesOrder as cancelled."""

    def get_context_data(self):
        """Add extra context data to the serializer."""
        order = self.context['order']

        return {'can_cancel': order.can_cancel}

    def save(self):
        """Save the serializer to cancel the order."""
        self.order.cancel_order()


class SalesOrderSerialAllocationSerializer(serializers.Serializer):
    """DRF serializer for allocation of serial numbers against a sales order / shipment."""

    class Meta:
        """Metaclass options."""

        fields = ['line_item', 'quantity', 'serial_numbers', 'shipment']

    line_item = serializers.PrimaryKeyRelatedField(
        queryset=order.models.SalesOrderLineItem.objects.all(),
        many=False,
        required=True,
        allow_null=False,
        label=_('Line Item'),
    )

    def validate_line_item(self, line_item):
        """Ensure that the line_item is valid."""
        order = self.context['order']

        # Ensure that the line item points to the correct order
        if line_item.order != order:
            raise ValidationError(_('Line item is not associated with this order'))

        return line_item

    quantity = serializers.IntegerField(
        min_value=1, required=True, allow_null=False, label=_('Quantity')
    )

    serial_numbers = serializers.CharField(
        label=_('Serial Numbers'),
        help_text=_('Enter serial numbers to allocate'),
        required=True,
        allow_blank=False,
    )

    shipment = serializers.PrimaryKeyRelatedField(
        queryset=order.models.SalesOrderShipment.objects.all(),
        many=False,
        required=False,
        allow_null=True,
        label=_('Shipment'),
    )

    def validate_shipment(self, shipment):
        """Validate the shipment.

        - Must point to the same order
        - Must not be shipped
        """
        order = self.context['order']

        if shipment and shipment.shipment_date is not None:
            raise ValidationError(_('Shipment has already been shipped'))

        if shipment and shipment.order != order:
            raise ValidationError(_('Shipment is not associated with this order'))

        return shipment

    def validate(self, data):
        """Validation for the serializer.

        - Ensure the serial_numbers and quantity fields match
        - Check that all serial numbers exist
        - Check that the serial numbers are not yet allocated
        """
        data = super().validate(data)

        line_item = data['line_item']
        quantity = data['quantity']
        serial_numbers = data['serial_numbers']

        part = line_item.part

        try:
            data['serials'] = extract_serial_numbers(
                serial_numbers, quantity, part.get_latest_serial_number(), part=part
            )
        except DjangoValidationError as e:
            raise ValidationError({'serial_numbers': e.messages})

        serials_not_exist = set()
        serials_unavailable = set()
        stock_items_to_allocate = []

        for serial in data['serials']:
            serial = str(serial).strip()

            items = stock.models.StockItem.objects.filter(
                part=part, serial=serial, quantity=1
            )

            if not items.exists():
                serials_not_exist.add(str(serial))
                continue

            stock_item = items[0]

            if not stock_item.in_stock:
                serials_unavailable.add(str(serial))
                continue

            if stock_item.unallocated_quantity() < 1:
                serials_unavailable.add(str(serial))
                continue

            # At this point, the serial number is valid, and can be added to the list
            stock_items_to_allocate.append(stock_item)

        if len(serials_not_exist) > 0:
            error_msg = _('No match found for the following serial numbers')
            error_msg += ': '
            error_msg += ','.join(sorted(serials_not_exist))

            raise ValidationError({'serial_numbers': error_msg})

        if len(serials_unavailable) > 0:
            error_msg = _('The following serial numbers are unavailable')
            error_msg += ': '
            error_msg += ','.join(sorted(serials_unavailable))

            raise ValidationError({'serial_numbers': error_msg})

        data['stock_items'] = stock_items_to_allocate

        return data

    def save(self):
        """Allocate stock items against the sales order."""
        data = self.validated_data

        line_item = data['line_item']
        stock_items = data['stock_items']
        shipment = data.get('shipment', None)

        allocations = []

        for stock_item in stock_items:
            # Create a new SalesOrderAllocation
            allocations.append(
                order.models.SalesOrderAllocation(
                    line=line_item, item=stock_item, quantity=1, shipment=shipment
                )
            )

        with transaction.atomic():
            order.models.SalesOrderAllocation.objects.bulk_create(allocations)


class SalesOrderShipmentAllocationSerializer(serializers.Serializer):
    """DRF serializer for allocation of stock items against a sales order / shipment."""

    class Meta:
        """Metaclass options."""

        fields = ['items', 'shipment']

    items = SalesOrderShipmentAllocationItemSerializer(many=True)

    shipment = serializers.PrimaryKeyRelatedField(
        queryset=order.models.SalesOrderShipment.objects.all(),
        many=False,
        required=False,
        allow_null=True,
        label=_('Shipment'),
    )

    def validate_shipment(self, shipment):
        """Run validation against the provided shipment instance."""
        order = self.context['order']

        if shipment and shipment.shipment_date is not None:
            raise ValidationError(_('Shipment has already been shipped'))

        if shipment and shipment.order != order:
            raise ValidationError(_('Shipment is not associated with this order'))

        return shipment

    def validate(self, data):
        """Serializer validation."""
        data = super().validate(data)

        # Extract SalesOrder from serializer context
        # order = self.context['order']

        items = data.get('items', [])

        if len(items) == 0:
            raise ValidationError(_('Allocation items must be provided'))

        return data

    def save(self):
        """Perform the allocation of items against this order."""
        data = self.validated_data

        items = data['items']
        shipment = data.get('shipment')

        with transaction.atomic():
            for entry in items:
                # Create a new SalesOrderAllocation
                allocation = order.models.SalesOrderAllocation(
                    line=entry.get('line_item'),
                    item=entry.get('stock_item'),
                    quantity=entry.get('quantity'),
                    shipment=shipment,
                )

                allocation.full_clean()
                allocation.save()


@register_importer()
class SalesOrderExtraLineSerializer(
    AbstractExtraLineSerializer, InvenTreeModelSerializer
):
    """Serializer for a SalesOrderExtraLine object."""

    class Meta(AbstractExtraLineMeta):
        """Metaclass options."""

        model = order.models.SalesOrderExtraLine

    order_detail = SalesOrderSerializer(
        source='order', many=False, read_only=True, allow_null=True
    )


@register_importer()
class ReturnOrderSerializer(
    NotesFieldMixin,
    InvenTreeCustomStatusSerializerMixin,
    AbstractOrderSerializer,
    TotalPriceMixin,
    InvenTreeModelSerializer,
):
    """Serializer for the ReturnOrder model class."""

    class Meta:
        """Metaclass options."""

        model = order.models.ReturnOrder

        fields = AbstractOrderSerializer.order_fields([
            'complete_date',
            'customer',
            'customer_detail',
            'customer_reference',
            'order_currency',
            'total_price',
        ])

        read_only_fields = ['creation_date']

    def __init__(self, *args, **kwargs):
        """Initialization routine for the serializer."""
        customer_detail = kwargs.pop('customer_detail', False)

        super().__init__(*args, **kwargs)

        if customer_detail is not True and not isGeneratingSchema():
            self.fields.pop('customer_detail', None)

    def skip_create_fields(self):
        """Skip these fields when instantiating a new object."""
        fields = super().skip_create_fields()

        return [*fields, 'duplicate']

    @staticmethod
    def annotate_queryset(queryset):
        """Custom annotation for the serializer queryset."""
        queryset = AbstractOrderSerializer.annotate_queryset(queryset)

        queryset = queryset.annotate(
            completed_lines=SubqueryCount(
                'lines', filter=~Q(outcome=ReturnOrderLineStatus.PENDING.value)
            )
        )

        queryset = queryset.annotate(
            overdue=Case(
                When(
                    order.models.ReturnOrder.overdue_filter(),
                    then=Value(True, output_field=BooleanField()),
                ),
                default=Value(False, output_field=BooleanField()),
            )
        )

        return queryset

    customer_detail = CompanyBriefSerializer(
        source='customer', many=False, read_only=True, allow_null=True
    )


class ReturnOrderHoldSerializer(OrderAdjustSerializer):
    """Serializers for holding a ReturnOrder."""

    def save(self):
        """Save the serializer to 'hold' the order."""
        self.order.hold_order()


class ReturnOrderIssueSerializer(OrderAdjustSerializer):
    """Serializer for issuing a ReturnOrder."""

    def save(self):
        """Save the serializer to 'issue' the order."""
        self.order.issue_order()


class ReturnOrderCancelSerializer(OrderAdjustSerializer):
    """Serializer for cancelling a ReturnOrder."""

    def save(self):
        """Save the serializer to 'cancel' the order."""
        self.order.cancel_order()


class ReturnOrderCompleteSerializer(OrderAdjustSerializer):
    """Serializer for completing a ReturnOrder."""

    def save(self):
        """Save the serializer to 'complete' the order."""
        self.order.complete_order()


class ReturnOrderLineItemReceiveSerializer(serializers.Serializer):
    """Serializer for receiving a single line item against a ReturnOrder."""

    class Meta:
        """Metaclass options."""

        fields = ['item', 'status']

    item = serializers.PrimaryKeyRelatedField(
        queryset=order.models.ReturnOrderLineItem.objects.all(),
        many=False,
        allow_null=False,
        required=True,
        label=_('Return order line item'),
    )

    status = stock.serializers.StockStatusCustomSerializer(
        default=None, required=False, allow_blank=True
    )

    def validate_line_item(self, item):
        """Validation for a single line item."""
        if item.order != self.context['order']:
            raise ValidationError(_('Line item does not match return order'))

        if item.received:
            raise ValidationError(_('Line item has already been received'))

        return item


class ReturnOrderReceiveSerializer(serializers.Serializer):
    """Serializer for receiving items against a ReturnOrder."""

    class Meta:
        """Metaclass options."""

        fields = ['items', 'location', 'note']

    items = ReturnOrderLineItemReceiveSerializer(many=True)

    location = serializers.PrimaryKeyRelatedField(
        queryset=stock.models.StockLocation.objects.all(),
        many=False,
        allow_null=False,
        required=True,
        label=_('Location'),
        help_text=_('Select destination location for received items'),
    )

    note = serializers.CharField(
        label=_('Note'),
        help_text=_('Additional note for incoming stock items'),
        required=False,
        default='',
        allow_blank=True,
    )

    def validate(self, data):
        """Perform data validation for this serializer."""
        order = self.context['order']
        if order.status != ReturnOrderStatus.IN_PROGRESS:
            raise ValidationError(
                _('Items can only be received against orders which are in progress')
            )

        data = super().validate(data)

        items = data.get('items', [])

        if len(items) == 0:
            raise ValidationError(_('Line items must be provided'))

        return data

    @transaction.atomic
    def save(self):
        """Saving this serializer marks the returned items as received."""
        order = self.context['order']
        request = self.context.get('request')

        data = self.validated_data
        items = data['items']
        location = data['location']

        with transaction.atomic():
            for item in items:
                line_item = item['item']

                order.receive_line_item(
                    line_item,
                    location,
                    request.user if request else None,
                    note=data.get('note', ''),
                    status=item.get('status', None),
                )


@register_importer()
class ReturnOrderLineItemSerializer(
    DataImportExportSerializerMixin,
    AbstractLineItemSerializer,
    InvenTreeModelSerializer,
):
    """Serializer for a ReturnOrderLineItem object."""

    class Meta:
        """Metaclass options."""

        model = order.models.ReturnOrderLineItem

        fields = [
            'pk',
            'order',
            'order_detail',
            'item',
            'item_detail',
            'quantity',
            'received_date',
            'outcome',
            'part_detail',
            'price',
            'price_currency',
            'link',
            'reference',
            'notes',
            'target_date',
            'link',
        ]

    def __init__(self, *args, **kwargs):
        """Initialization routine for the serializer."""
        order_detail = kwargs.pop('order_detail', False)
        item_detail = kwargs.pop('item_detail', False)
        part_detail = kwargs.pop('part_detail', False)

        super().__init__(*args, **kwargs)

        if isGeneratingSchema():
            return

        if not order_detail:
            self.fields.pop('order_detail', None)

        if not item_detail:
            self.fields.pop('item_detail', None)

        if not part_detail:
            self.fields.pop('part_detail', None)

    order_detail = ReturnOrderSerializer(
        source='order', many=False, read_only=True, allow_null=True
    )

    quantity = serializers.FloatField(
        label=_('Quantity'), help_text=_('Quantity to return')
    )

    item_detail = stock.serializers.StockItemSerializer(
        source='item', many=False, read_only=True, allow_null=True
    )

    part_detail = PartBriefSerializer(
        source='item.part', many=False, read_only=True, allow_null=True
    )

    price = InvenTreeMoneySerializer(allow_null=True)
    price_currency = InvenTreeCurrencySerializer(help_text=_('Line price currency'))


@register_importer()
class ReturnOrderExtraLineSerializer(
    AbstractExtraLineSerializer, InvenTreeModelSerializer
):
    """Serializer for a ReturnOrderExtraLine object."""

    class Meta(AbstractExtraLineMeta):
        """Metaclass options."""

        model = order.models.ReturnOrderExtraLine

    order_detail = ReturnOrderSerializer(
        source='order', many=False, read_only=True, allow_null=True
    )
