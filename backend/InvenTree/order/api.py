"""JSON API for the Order app."""

from decimal import Decimal
from typing import cast

from django.conf import settings
from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User
from django.db.models import F, Q
from django.http.response import JsonResponse
from django.urls import include, path, re_path
from django.utils.translation import gettext_lazy as _

import rest_framework.serializers
from django_filters import rest_framework as rest_filters
from django_ical.views import ICalFeed
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import status
from rest_framework.response import Response

import build.models
import common.models
import common.settings
import company.models
import stock.models as stock_models
from data_exporter.mixins import DataExportViewMixin
from generic.states.api import StatusView
from InvenTree.api import BulkUpdateMixin, ListCreateDestroyAPIView, MetadataView
from InvenTree.filters import (
    SEARCH_ORDER_FILTER,
    SEARCH_ORDER_FILTER_ALIAS,
    InvenTreeDateFilter,
)
from InvenTree.helpers import str2bool
from InvenTree.helpers_model import construct_absolute_url, get_base_url
from InvenTree.mixins import CreateAPI, ListAPI, ListCreateAPI, RetrieveUpdateDestroyAPI
from order import models, serializers
from order.status_codes import (
    PurchaseOrderStatus,
    PurchaseOrderStatusGroups,
    ReturnOrderLineStatus,
    ReturnOrderStatus,
    SalesOrderStatus,
    SalesOrderStatusGroups,
)
from part.models import Part
from users.models import Owner

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Register fonts
pdfmetrics.registerFont(TTFont("DejaVuSans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))

class GeneralExtraLineList(DataExportViewMixin):
    """General template for ExtraLine API classes."""

    def get_serializer(self, *args, **kwargs):
        """Return the serializer instance for this endpoint."""
        try:
            params = self.request.query_params3

            kwargs['order_detail'] = str2bool(params.get('order_detail', False))
        except AttributeError:
            pass

        kwargs['context'] = self.get_serializer_context()

        return super().get_serializer(*args, **kwargs)

    def get_queryset(self, *args, **kwargs):
        """Return the annotated queryset for this endpoint."""
        queryset = super().get_queryset(*args, **kwargs)

        queryset = queryset.prefetch_related('order')

        return queryset

    filter_backends = SEARCH_ORDER_FILTER

    ordering_fields = ['quantity', 'notes', 'reference']

    search_fields = ['quantity', 'notes', 'reference', 'description']

    filterset_fields = ['order']


class OrderCreateMixin:
    """Mixin class which handles order creation via API."""

    def create(self, request, *args, **kwargs):
        """Save user information on order creation."""
        serializer = self.get_serializer(data=self.clean_data(request.data))
        serializer.is_valid(raise_exception=True)

        item = serializer.save()
        item.created_by = request.user
        item.save()

        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )


class OrderFilter(rest_filters.FilterSet):
    """Base class for custom API filters for the OrderList endpoint."""

    # Filter against order status
    status = rest_filters.NumberFilter(label=_('Order Status'), method='filter_status')

    def filter_status(self, queryset, name, value):
        """Filter by integer status code.

        Note: Also account for the possibility of a custom status code.
        """
        q1 = Q(status=value, status_custom_key__isnull=True)
        q2 = Q(status_custom_key=value)

        return queryset.filter(q1 | q2).distinct()

    # Exact match for reference
    reference = rest_filters.CharFilter(
        label=_('Order Reference'), field_name='reference', lookup_expr='iexact'
    )

    assigned_to_me = rest_filters.BooleanFilter(
        label=_('Assigned to me'), method='filter_assigned_to_me'
    )

    def filter_assigned_to_me(self, queryset, name, value):
        """Filter by orders which are assigned to the current user."""
        # Work out who "me" is!
        owners = Owner.get_owners_matching_user(self.request.user)

        if str2bool(value):
            return queryset.filter(responsible__in=owners)
        return queryset.exclude(responsible__in=owners)

    overdue = rest_filters.BooleanFilter(label='overdue', method='filter_overdue')

    def filter_overdue(self, queryset, name, value):
        """Generic filter for determining if an order is 'overdue'.

        Note that the overdue_filter() classmethod must be defined for the model
        """
        if str2bool(value):
            return queryset.filter(self.Meta.model.overdue_filter())
        return queryset.exclude(self.Meta.model.overdue_filter())

    outstanding = rest_filters.BooleanFilter(
        label=_('Outstanding'), method='filter_outstanding'
    )

    def filter_outstanding(self, queryset, name, value):
        """Generic filter for determining if an order is 'outstanding'."""
        if str2bool(value):
            return queryset.filter(status__in=self.Meta.model.get_status_class().OPEN)
        return queryset.exclude(status__in=self.Meta.model.get_status_class().OPEN)

    project_code = rest_filters.ModelChoiceFilter(
        queryset=common.models.ProjectCode.objects.all(),
        field_name='project_code',
        label=_('Project Code'),
    )

    has_project_code = rest_filters.BooleanFilter(
        method='filter_has_project_code', label=_('Has Project Code')
    )

    def filter_has_project_code(self, queryset, name, value):
        """Filter by whether or not the order has a project code."""
        if str2bool(value):
            return queryset.exclude(project_code=None)
        return queryset.filter(project_code=None)

    assigned_to = rest_filters.ModelChoiceFilter(
        queryset=Owner.objects.all(), field_name='responsible', label=_('Responsible')
    )

    created_by = rest_filters.ModelChoiceFilter(
        queryset=User.objects.all(), field_name='created_by', label=_('Created By')
    )

    created_before = InvenTreeDateFilter(
        label=_('Created Before'), field_name='creation_date', lookup_expr='lt'
    )

    created_after = InvenTreeDateFilter(
        label=_('Created After'), field_name='creation_date', lookup_expr='gt'
    )

    has_start_date = rest_filters.BooleanFilter(
        label=_('Has Start Date'), method='filter_has_start_date'
    )

    def filter_has_start_date(self, queryset, name, value):
        """Filter by whether or not the order has a start date."""
        return queryset.filter(start_date__isnull=not str2bool(value))

    start_date_before = InvenTreeDateFilter(
        label=_('Start Date Before'), field_name='start_date', lookup_expr='lt'
    )

    start_date_after = InvenTreeDateFilter(
        label=_('Start Date After'), field_name='start_date', lookup_expr='gt'
    )

    has_target_date = rest_filters.BooleanFilter(
        label=_('Has Target Date'), method='filter_has_target_date'
    )

    def filter_has_target_date(self, queryset, name, value):
        """Filter by whether or not the order has a target date."""
        return queryset.filter(target_date__isnull=not str2bool(value))

    target_date_before = InvenTreeDateFilter(
        label=_('Target Date Before'), field_name='target_date', lookup_expr='lt'
    )

    target_date_after = InvenTreeDateFilter(
        label=_('Target Date After'), field_name='target_date', lookup_expr='gt'
    )

    min_date = InvenTreeDateFilter(label=_('Min Date'), method='filter_min_date')

    def filter_min_date(self, queryset, name, value):
        """Filter the queryset to include orders *after* a specified date.

        This is used in combination with filter_max_date,
        to provide a queryset which matches a particular range of dates.

        In particular, this is used in the UI for the calendar view.
        """
        q1 = Q(
            creation_date__gte=value, issue_date__isnull=True, start_date__isnull=True
        )
        q2 = Q(issue_date__gte=value, start_date__isnull=True)
        q3 = Q(start_date__gte=value)
        q4 = Q(target_date__gte=value)

        return queryset.filter(q1 | q2 | q3 | q4).distinct()

    max_date = InvenTreeDateFilter(label=_('Max Date'), method='filter_max_date')

    def filter_max_date(self, queryset, name, value):
        """Filter the queryset to include orders *before* a specified date.

        This is used in combination with filter_min_date,
        to provide a queryset which matches a particular range of dates.

        In particular, this is used in the UI for the calendar view.
        """
        q1 = Q(
            creation_date__lte=value, issue_date__isnull=True, start_date__isnull=True
        )
        q2 = Q(issue_date__lte=value, start_date__isnull=True)
        q3 = Q(start_date__lte=value)
        q4 = Q(target_date__lte=value)

        return queryset.filter(q1 | q2 | q3 | q4).distinct()


class LineItemFilter(rest_filters.FilterSet):
    """Base class for custom API filters for order line item list(s)."""

    # Filter by order status
    order_status = rest_filters.NumberFilter(
        label=_('Order Status'), field_name='order__status'
    )

    has_pricing = rest_filters.BooleanFilter(
        label=_('Has Pricing'), method='filter_has_pricing'
    )

    def filter_has_pricing(self, queryset, name, value):
        """Filter by whether or not the line item has pricing information."""
        filters = {self.Meta.price_field: None}

        if str2bool(value):
            return queryset.exclude(**filters)
        return queryset.filter(**filters)


class PurchaseOrderFilter(OrderFilter):
    """Custom API filters for the PurchaseOrderList endpoint."""

    class Meta:
        """Metaclass options."""

        model = models.PurchaseOrder
        fields = ['supplier']

    part = rest_filters.ModelChoiceFilter(
        queryset=Part.objects.all(),
        field_name='part',
        label=_('Part'),
        method='filter_part',
    )

    @extend_schema_field(rest_framework.serializers.IntegerField(help_text=_('Part')))
    def filter_part(self, queryset, name, part: Part):
        """Filter by provided Part instance."""
        orders = part.purchase_orders()

        return queryset.filter(pk__in=[o.pk for o in orders])

    supplier_part = rest_filters.ModelChoiceFilter(
        queryset=company.models.SupplierPart.objects.all(),
        label=_('Supplier Part'),
        method='filter_supplier_part',
    )

    @extend_schema_field(
        rest_framework.serializers.IntegerField(help_text=_('Supplier Part'))
    )
    def filter_supplier_part(
        self, queryset, name, supplier_part: company.models.SupplierPart
    ):
        """Filter by provided SupplierPart instance."""
        orders = supplier_part.purchase_orders()

        return queryset.filter(pk__in=[o.pk for o in orders])

    completed_before = InvenTreeDateFilter(
        label=_('Completed Before'), field_name='complete_date', lookup_expr='lt'
    )

    completed_after = InvenTreeDateFilter(
        label=_('Completed After'), field_name='complete_date', lookup_expr='gt'
    )

    external_build = rest_filters.ModelChoiceFilter(
        queryset=build.models.Build.objects.filter(external=True),
        method='filter_external_build',
        label=_('External Build Order'),
    )

    @extend_schema_field(
        rest_framework.serializers.IntegerField(help_text=_('External Build Order'))
    )
    def filter_external_build(self, queryset, name, build):
        """Filter to only include orders which fill fulfil the provided Build Order.

        To achieve this, we return any order which has a line item which is allocated to the build order.
        """
        return queryset.filter(lines__build_order=build).distinct()


class PurchaseOrderMixin:
    """Mixin class for PurchaseOrder endpoints."""

    queryset = models.PurchaseOrder.objects.all()
    serializer_class = serializers.PurchaseOrderSerializer

    def get_serializer(self, *args, **kwargs):
        """Return the serializer instance for this endpoint."""
        try:
            kwargs['supplier_detail'] = str2bool(
                self.request.query_params.get('supplier_detail', False)
            )
        except AttributeError:
            pass

        # Ensure the request context is passed through
        kwargs['context'] = self.get_serializer_context()

        return super().get_serializer(*args, **kwargs)

    def get_queryset(self, *args, **kwargs):
        """Return the annotated queryset for this endpoint."""
        queryset = super().get_queryset(*args, **kwargs)

        queryset = queryset.prefetch_related(
            'supplier', 'project_code', 'lines', 'responsible'
        )

        queryset = serializers.PurchaseOrderSerializer.annotate_queryset(queryset)

        return queryset


class PurchaseOrderList(
    PurchaseOrderMixin, OrderCreateMixin, DataExportViewMixin, ListCreateAPI
):
    """API endpoint for accessing a list of PurchaseOrder objects.

    - GET: Return list of PurchaseOrder objects (with filters)
    - POST: Create a new PurchaseOrder object
    """

    filterset_class = PurchaseOrderFilter
    filter_backends = SEARCH_ORDER_FILTER_ALIAS

    ordering_field_aliases = {
        'reference': ['reference_int', 'reference'],
        'project_code': ['project_code__code'],
    }

    search_fields = [
        'reference',
        'supplier__name',
        'supplier_reference',
        'project_code__code',
        'description',
    ]

    ordering_fields = [
        'creation_date',
        'created_by',
        'reference',
        'supplier__name',
        'start_date',
        'target_date',
        'complete_date',
        'line_items',
        'status',
        'responsible',
        'total_price',
        'project_code',
    ]

    ordering = '-reference'


class PurchaseOrderDetail(PurchaseOrderMixin, RetrieveUpdateDestroyAPI):
    """API endpoint for detail view of a PurchaseOrder object."""


class PurchaseOrderContextMixin:
    """Mixin to add purchase order object as serializer context variable."""

    queryset = models.PurchaseOrder.objects.all()

    def get_serializer_context(self):
        """Add the PurchaseOrder object to the serializer context."""
        context = super().get_serializer_context()

        # Pass the purchase order through to the serializer for validation
        try:
            context['order'] = models.PurchaseOrder.objects.get(
                pk=self.kwargs.get('pk', None)
            )
        except Exception:
            pass

        context['request'] = self.request

        return context


class PurchaseOrderHold(PurchaseOrderContextMixin, CreateAPI):
    """API endpoint to place a PurchaseOrder on hold."""

    serializer_class = serializers.PurchaseOrderHoldSerializer


class PurchaseOrderCancel(PurchaseOrderContextMixin, CreateAPI):
    """API endpoint to 'cancel' a purchase order.

    The purchase order must be in a state which can be cancelled
    """

    serializer_class = serializers.PurchaseOrderCancelSerializer


class PurchaseOrderComplete(PurchaseOrderContextMixin, CreateAPI):
    """API endpoint to 'complete' a purchase order."""

    serializer_class = serializers.PurchaseOrderCompleteSerializer


class PurchaseOrderIssue(PurchaseOrderContextMixin, CreateAPI):
    """API endpoint to 'issue' (place) a PurchaseOrder."""

    serializer_class = serializers.PurchaseOrderIssueSerializer


class PurchaseOrderReceive(PurchaseOrderContextMixin, CreateAPI):
    """API endpoint to receive stock items against a PurchaseOrder.

    - The purchase order is specified in the URL.
    - Items to receive are specified as a list called "items" with the following options:
        - line_item: pk of the PO Line item
        - supplier_part: pk value of the supplier part
        - quantity: quantity to receive
        - status: stock item status
        - expiry_date: stock item expiry date (optional)
        - location: destination for stock item (optional)
        - batch_code: the batch code for this stock item
        - serial_numbers: serial numbers for this stock item
    - A global location must also be specified. This is used when no locations are specified for items, and no location is given in the PO line item
    """

    queryset = models.PurchaseOrderLineItem.objects.none()

    serializer_class = serializers.PurchaseOrderReceiveSerializer


class PurchaseOrderLineItemFilter(LineItemFilter):
    """Custom filters for the PurchaseOrderLineItemList endpoint."""

    class Meta:
        """Metaclass options."""

        price_field = 'purchase_price'
        model = models.PurchaseOrderLineItem
        fields = []

    order = rest_filters.ModelChoiceFilter(
        queryset=models.PurchaseOrder.objects.all(),
        field_name='order',
        label=_('Order'),
    )

    order_complete = rest_filters.BooleanFilter(
        label=_('Order Complete'), method='filter_order_complete'
    )

    def filter_order_complete(self, queryset, name, value):
        """Filter by whether the order is 'complete' or not."""
        if str2bool(value):
            return queryset.filter(order__status=PurchaseOrderStatus.COMPLETE.value)

        return queryset.exclude(order__status=PurchaseOrderStatus.COMPLETE.value)

    part = rest_filters.ModelChoiceFilter(
        queryset=company.models.SupplierPart.objects.all(),
        field_name='part',
        label=_('Supplier Part'),
    )

    include_variants = rest_filters.BooleanFilter(
        label=_('Include Variants'), method='filter_include_variants'
    )

    def filter_include_variants(self, queryset, name, value):
        """Filter by whether or not to include variants of the selected part.

        Note:
        - This filter does nothing by itself, and requires the 'base_part' filter to be set.
        - Refer to the 'filter_base_part' method for more information.
        """
        return queryset

    base_part = rest_filters.ModelChoiceFilter(
        queryset=Part.objects.filter(purchaseable=True),
        method='filter_base_part',
        label=_('Internal Part'),
    )

    @extend_schema_field(
        rest_framework.serializers.IntegerField(help_text=_('Internal Part'))
    )
    def filter_base_part(self, queryset, name, base_part):
        """Filter by the 'base_part' attribute.

        Note:
        - If "include_variants" is True, include all variants of the selected part
        - Otherwise, just filter by the selected part
        """
        include_variants = str2bool(self.data.get('include_variants', False))

        if include_variants:
            parts = base_part.get_descendants(include_self=True)
            return queryset.filter(part__part__in=parts)
        else:
            return queryset.filter(part__part=base_part)

    pending = rest_filters.BooleanFilter(
        method='filter_pending', label=_('Order Pending')
    )

    def filter_pending(self, queryset, name, value):
        """Filter by "pending" status (order status = pending)."""
        if str2bool(value):
            return queryset.filter(order__status__in=PurchaseOrderStatusGroups.OPEN)
        return queryset.exclude(order__status__in=PurchaseOrderStatusGroups.OPEN)

    received = rest_filters.BooleanFilter(
        label=_('Items Received'), method='filter_received'
    )

    def filter_received(self, queryset, name, value):
        """Filter by lines which are "received" (or "not" received).

        A line is considered "received" when received >= quantity
        """
        q = Q(received__gte=F('quantity'))

        if str2bool(value):
            return queryset.filter(q)
        # Only count "pending" orders
        return queryset.exclude(q).filter(
            order__status__in=PurchaseOrderStatusGroups.OPEN
        )


class PurchaseOrderLineItemMixin:
    """Mixin class for PurchaseOrderLineItem endpoints."""

    queryset = models.PurchaseOrderLineItem.objects.all()
    serializer_class = serializers.PurchaseOrderLineItemSerializer

    def get_queryset(self, *args, **kwargs):
        """Return annotated queryset for this endpoint."""
        queryset = super().get_queryset(*args, **kwargs)

        queryset = serializers.PurchaseOrderLineItemSerializer.annotate_queryset(
            queryset
        )

        return queryset

    def get_serializer(self, *args, **kwargs):
        """Return serializer instance for this endpoint."""
        try:
            kwargs['part_detail'] = str2bool(
                self.request.query_params.get('part_detail', False)
            )
            kwargs['order_detail'] = str2bool(
                self.request.query_params.get('order_detail', False)
            )
        except AttributeError:
            pass

        kwargs['context'] = self.get_serializer_context()

        return super().get_serializer(*args, **kwargs)

    def perform_update(self, serializer):
        """Override the perform_update method to auto-update pricing if required."""
        super().perform_update(serializer)

        # possibly auto-update pricing based on the supplier part pricing data
        if serializer.validated_data.get('auto_pricing', True):
            serializer.instance.update_pricing()


class PurchaseOrderLineItemList(
    PurchaseOrderLineItemMixin, DataExportViewMixin, ListCreateDestroyAPIView
):
    """API endpoint for accessing a list of PurchaseOrderLineItem objects.

    - GET: Return a list of PurchaseOrder Line Item objects
    - POST: Create a new PurchaseOrderLineItem object
    """

    filterset_class = PurchaseOrderLineItemFilter

    def create(self, request, *args, **kwargs):
        """Create or update a new PurchaseOrderLineItem object."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = cast(dict, serializer.validated_data)

        # possibly merge duplicate items
        line_item = None
        if data.get('merge_items', True):
            other_line = models.PurchaseOrderLineItem.objects.filter(
                part=data.get('part'),
                order=data.get('order'),
                target_date=data.get('target_date'),
                destination=data.get('destination'),
            ).first()

            if other_line is not None:
                other_line.quantity += Decimal(data.get('quantity', 0))
                other_line.save()

                line_item = other_line

        # otherwise create a new line item
        if line_item is None:
            line_item = serializer.save()

        # possibly auto-update pricing based on the supplier part pricing data
        if data.get('auto_pricing', True) and isinstance(
            line_item, models.PurchaseOrderLineItem
        ):
            line_item.update_pricing()

        serializer = serializers.PurchaseOrderLineItemSerializer(line_item)
        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )

    filter_backends = SEARCH_ORDER_FILTER_ALIAS

    ordering_field_aliases = {
        'MPN': 'part__manufacturer_part__MPN',
        'SKU': 'part__SKU',
        'IPN': 'part__part__IPN',
        'part_name': 'part__part__name',
        'order': 'order__reference',
        'status': 'order__status',
        'complete_date': 'order__complete_date',
    }

    ordering_fields = [
        'MPN',
        'part_name',
        'purchase_price',
        'quantity',
        'received',
        'reference',
        'SKU',
        'IPN',
        'total_price',
        'target_date',
        'order',
        'status',
        'complete_date',
    ]

    search_fields = [
        'part__part__name',
        'part__part__description',
        'part__manufacturer_part__MPN',
        'part__SKU',
        'reference',
    ]


class PurchaseOrderLineItemDetail(PurchaseOrderLineItemMixin, RetrieveUpdateDestroyAPI):
    """Detail API endpoint for PurchaseOrderLineItem object."""


class PurchaseOrderExtraLineList(GeneralExtraLineList, ListCreateAPI):
    """API endpoint for accessing a list of PurchaseOrderExtraLine objects."""

    queryset = models.PurchaseOrderExtraLine.objects.all()
    serializer_class = serializers.PurchaseOrderExtraLineSerializer


class PurchaseOrderExtraLineDetail(RetrieveUpdateDestroyAPI):
    """API endpoint for detail view of a PurchaseOrderExtraLine object."""

    queryset = models.PurchaseOrderExtraLine.objects.all()
    serializer_class = serializers.PurchaseOrderExtraLineSerializer


def compute_fifo_fulfillment(queryset):
    """
    Check sales order fulfillment based on FIFO allocation using
    actual available stock per part.
    Only considers pending sales orders.
    Returns a dict {order_id: fulfilled_boolean}.
    """

    # Only pending sales orders
    pending_orders = queryset.filter(status=10)  # 10 = Pending

    # Build available stock per part: total_stock - allocations
    part_ids = pending_orders.values_list('lines__part', flat=True).distinct()
    parts = Part.objects.filter(id__in=part_ids)
    part_stock = {}
    # inside compute_fifo_fulfillment
    for p in parts:
        # Ensure numeric values
        build_alloc = Decimal(0)
        sales_alloc = Decimal(0)

        if hasattr(p, 'build_order_allocations') and callable(p.build_order_allocations):
            val = p.build_order_allocations()
            if isinstance(val, Decimal):
                build_alloc = val
            else:
                build_alloc = val.aggregate_total() if hasattr(val, 'aggregate_total') else Decimal(0)

        if hasattr(p, 'sales_order_allocations') and callable(p.sales_order_allocations):
            val = p.sales_order_allocations()
            if isinstance(val, Decimal):
                sales_alloc = val
            else:
                sales_alloc = val.aggregate_total() if hasattr(val, 'aggregate_total') else Decimal(0)

        part_stock[p.id] = p.total_stock - build_alloc - sales_alloc
        print("Part ID:", p.id, "Total Stock:", p.total_stock, "Build Alloc:", build_alloc, "Sales Alloc:", sales_alloc, "Available:", part_stock[p.id])

    # Prefetch lines for all pending orders
    sales_orders = pending_orders.order_by('creation_date').prefetch_related('lines')

    order_status = {}
    for order in sales_orders:
        fulfilled = True
        for line in order.lines.all():
            if not line.part_id:
                continue
            needed = line.quantity
            available = part_stock.get(line.part_id, Decimal(0))
            if available >= needed:
                part_stock[line.part_id] -= needed
            else:
                fulfilled = False
        order_status[order.id] = fulfilled

    return order_status


class SalesOrderFilter(OrderFilter):
    """Custom API filters for the SalesOrderList endpoint."""

    class Meta:
        """Metaclass options."""

        model = models.SalesOrder
        fields = ['customer']

    include_variants = rest_filters.BooleanFilter(
        label=_('Include Variants'), method='filter_include_variants'
    )

    def filter_include_variants(self, queryset, name, value):
        """Filter by whether or not to include variants of the selected part.

        Note:
        - This filter does nothing by itself, and requires the 'part' filter to be set.
        - Refer to the 'filter_part' method for more information.
        """
        return queryset

    part = rest_filters.ModelChoiceFilter(
        queryset=Part.objects.all(), field_name='part', method='filter_part'
    )

    @extend_schema_field(OpenApiTypes.INT)
    def filter_part(self, queryset, name, part):
        """Filter SalesOrder by selected 'part'.

        Note:
        - If 'include_variants' is set to True, then all variants of the selected part will be included.
        - Otherwise, just filter by the selected part.
        """
        include_variants = str2bool(self.data.get('include_variants', False))

        # Construct a queryset of parts to filter by
        if include_variants:
            parts = part.get_descendants(include_self=True)
        else:
            parts = Part.objects.filter(pk=part.pk)

        # Now that we have a queryset of parts, find all the matching sales orders
        line_items = models.SalesOrderLineItem.objects.filter(part__in=parts)

        # Generate a list of ID values for the matching sales orders
        sales_orders = line_items.values_list('order', flat=True).distinct()

        # Now we have a list of matching IDs, filter the queryset
        return queryset.filter(pk__in=sales_orders)

    completed_before = InvenTreeDateFilter(
        label=_('Completed Before'), field_name='shipment_date', lookup_expr='lt'
    )

    completed_after = InvenTreeDateFilter(
        label=_('Completed After'), field_name='shipment_date', lookup_expr='gt'
    )
    
    # --- NEW: Filter by Part Name with include/exclude option ---
    part_name = rest_filters.CharFilter(
        method='filter_by_part_name',
        label='Filter by Part Name',
        help_text='Find orders that include or exclude a part with this name'
    )

    include_part = rest_filters.BooleanFilter(
        method='filter_by_part_name',
        label='Include Part',
        help_text='If true, show orders that include the part; if false, show orders without it'
    )

    def filter_by_part_name(self, queryset, name, value):
        # Retrieve the value from request (works for both part_name and include_part)
        part_name = self.data.get('part_name', None)
        include_part = str2bool(self.data.get('include_part', 'true'))  # default True

        if not part_name:
            return queryset

        # Find parts matching the name
        part_ids = Part.objects.filter(name__icontains=part_name).values_list('id', flat=True)

        # Include orders containing these parts
        if include_part:
            return queryset.filter(lines__part_id__in=part_ids).distinct()
        # Exclude orders containing these parts
        else:
            return queryset.exclude(lines__part_id__in=part_ids).distinct()


    region_type = rest_filters.CharFilter(
        method='filter_region_type',
        label=_('Order Region'),
        help_text=_('Filter sales orders by region: "india" or "international"')
    )

    def filter_region_type(self, queryset, name, value):
        """
        Filter sales orders based on region: 'india' or 'international'
        """
        if not value:
            return queryset

        value = value.strip().lower()

        if value == 'india':
            return queryset.filter(
                Q(country__iexact='India') | Q(country__iexact='IN')
            )

        elif value == 'international':
            return queryset.exclude(
                Q(country__iexact='India') | Q(country__iexact='IN')
            )

        return queryset

    fifo_stock_status = rest_filters.CharFilter(
        method='filter_fifo_stock_status',
        label=_('FIFO Stock Status'),
        help_text=_('Filter orders based on stock fulfillment (complete/pending)')
    )

    def filter_fifo_stock_status(self, queryset, name, value):
        """
        Filter sales orders based on FIFO stock allocation.
        Preserves other applied filters, but computes FIFO globally
        for all pending orders of the involved parts.
        """
        if not value:
            return queryset

        value = value.strip().lower()

        # Start with the filtered queryset
        filtered_orders = queryset.filter(status=10)

        if not filtered_orders.exists():
            return queryset.none()

        # --- Key Fix: Get all parts in the filtered queryset ---
        part_ids = models.SalesOrderLineItem.objects.filter(order__in=filtered_orders).values_list('part_id', flat=True).distinct()

        # --- Compute FIFO across *all* pending orders that use these parts ---
        all_pending_for_parts = models.SalesOrder.objects.filter(
            status=10,
            lines__part_id__in=part_ids
        ).distinct()

        order_status = compute_fifo_fulfillment(all_pending_for_parts)

        if value == 'complete':
            order_ids = [oid for oid, fulfilled in order_status.items() if fulfilled]
        elif value == 'pending':
            order_ids = [oid for oid, fulfilled in order_status.items() if not fulfilled]
        else:
            return queryset

        # Return only those in the original filtered queryset
        return queryset.filter(pk__in=order_ids)

    # ✅ NEW: Gujarat filter (statewise orders)
    gujarat_orders = rest_filters.BooleanFilter(
        method='filter_gujarat_orders',
        label=_('Include Gujarat Orders'),
        help_text=_('If true, show only Gujarat-based orders in India; if false, show only non-Gujarat India orders')
    )

    def filter_gujarat_orders(self, queryset, name, value):
        include_gujarat = str(value).lower() in ['1', 'true', 'yes']

        # Include orders even if address is missing, but prefer those in India
        qs = queryset.filter(
            Q(customer__addresses__country__icontains='India') 
        )

        if include_gujarat:
            return qs.filter(customer__addresses__province__icontains='gujarat')
        else:
            return qs.exclude(customer__addresses__province__icontains='gujarat')

class SalesOrderMixin:
    """Mixin class for SalesOrder endpoints."""

    queryset = models.SalesOrder.objects.all()
    serializer_class = serializers.SalesOrderSerializer

    def get_serializer(self, *args, **kwargs):
        """Return serializer instance for this endpoint."""
        try:
            kwargs['customer_detail'] = str2bool(
                self.request.query_params.get('customer_detail', False)
            )
        except AttributeError:
            pass

        # Ensure the context is passed through to the serializer
        kwargs['context'] = self.get_serializer_context()

        return super().get_serializer(*args, **kwargs)

    def get_queryset(self, *args, **kwargs):
        """Return annotated queryset for this endpoint."""
        queryset = super().get_queryset(*args, **kwargs)

        queryset = queryset.prefetch_related(
            'customer', 'responsible', 'project_code', 'lines'
        )

        queryset = serializers.SalesOrderSerializer.annotate_queryset(queryset)

        return queryset


class SalesOrderList(
    SalesOrderMixin, OrderCreateMixin, DataExportViewMixin, ListCreateAPI
):
    """API endpoint for accessing a list of SalesOrder objects.

    - GET: Return list of SalesOrder objects (with filters)
    - POST: Create a new SalesOrder
    """

    filterset_class = SalesOrderFilter

    filter_backends = SEARCH_ORDER_FILTER_ALIAS

    ordering_field_aliases = {
        'reference': ['reference_int', 'reference'],
        'project_code': ['project_code__code'],
    }

    filterset_fields = ['customer']

    ordering_fields = [
        'creation_date',
        'created_by',
        'reference',
        'customer__name',
        'customer_reference',
        'status',
        'start_date',
        'target_date',
        'line_items',
        'shipment_date',
        'total_price',
        'project_code',
    ]

    search_fields = [
        'customer__name',
        'customer__individual_name',   # 👈 Added
        'customer__email',             # 👈 Added
        'reference',
        'description',
        'customer_reference',
        'project_code__code',
    ]   

    ordering = '-reference'


class SalesOrderDetail(SalesOrderMixin, RetrieveUpdateDestroyAPI):
    """API endpoint for detail view of a SalesOrder object."""


class SalesOrderLineItemFilter(LineItemFilter):
    """Custom filters for SalesOrderLineItemList endpoint."""

    class Meta:
        """Metaclass options."""

        price_field = 'sale_price'
        model = models.SalesOrderLineItem
        fields = []

    order = rest_filters.ModelChoiceFilter(
        queryset=models.SalesOrder.objects.all(), field_name='order', label=_('Order')
    )

    part = rest_filters.ModelChoiceFilter(
        queryset=Part.objects.all(), field_name='part', label=_('Part')
    )

    allocated = rest_filters.BooleanFilter(
        label=_('Allocated'), method='filter_allocated'
    )

    def filter_allocated(self, queryset, name, value):
        """Filter by lines which are 'allocated'.

        A line is 'allocated' when allocated >= quantity
        """
        q = Q(allocated__gte=F('quantity'))

        if str2bool(value):
            return queryset.filter(q)
        return queryset.exclude(q)

    completed = rest_filters.BooleanFilter(
        label=_('Completed'), method='filter_completed'
    )

    def filter_completed(self, queryset, name, value):
        """Filter by lines which are "completed".

        A line is 'completed' when shipped >= quantity
        """
        q = Q(shipped__gte=F('quantity'))

        if str2bool(value):
            return queryset.filter(q)
        return queryset.exclude(q)

    order_complete = rest_filters.BooleanFilter(
        label=_('Order Complete'), method='filter_order_complete'
    )

    def filter_order_complete(self, queryset, name, value):
        """Filter by whether the order is 'complete' or not."""
        if str2bool(value):
            return queryset.filter(order__status__in=SalesOrderStatusGroups.COMPLETE)

        return queryset.exclude(order__status__in=SalesOrderStatusGroups.COMPLETE)

    order_outstanding = rest_filters.BooleanFilter(
        label=_('Order Outstanding'), method='filter_order_outstanding'
    )

    def filter_order_outstanding(self, queryset, name, value):
        """Filter by whether the order is 'outstanding' or not."""
        if str2bool(value):
            return queryset.filter(order__status__in=SalesOrderStatusGroups.OPEN)

        return queryset.exclude(order__status__in=SalesOrderStatusGroups.OPEN)


class SalesOrderLineItemMixin:
    """Mixin class for SalesOrderLineItem endpoints."""

    queryset = models.SalesOrderLineItem.objects.all()
    serializer_class = serializers.SalesOrderLineItemSerializer

    def get_serializer(self, *args, **kwargs):
        """Return serializer for this endpoint with extra data as requested."""
        try:
            params = self.request.query_params

            kwargs['part_detail'] = str2bool(params.get('part_detail', False))
            kwargs['order_detail'] = str2bool(params.get('order_detail', False))
            kwargs['customer_detail'] = str2bool(params.get('customer_detail', False))

        except AttributeError:
            pass

        kwargs['context'] = self.get_serializer_context()

        return super().get_serializer(*args, **kwargs)

    def get_queryset(self, *args, **kwargs):
        """Return annotated queryset for this endpoint."""
        queryset = super().get_queryset(*args, **kwargs)

        queryset = queryset.prefetch_related(
            'part',
            'part__stock_items',
            'allocations',
            'allocations__shipment',
            'allocations__item__part',
            'allocations__item__location',
            'order',
            'order__stock_items',
        )

        queryset = queryset.select_related('part__pricing_data')

        queryset = serializers.SalesOrderLineItemSerializer.annotate_queryset(queryset)

        return queryset


class SalesOrderLineItemList(
    SalesOrderLineItemMixin, DataExportViewMixin, ListCreateAPI
):
    """API endpoint for accessing a list of SalesOrderLineItem objects."""

    filterset_class = SalesOrderLineItemFilter

    filter_backends = SEARCH_ORDER_FILTER_ALIAS

    ordering_fields = [
        'customer',
        'order',
        'part',
        'part__name',
        'quantity',
        'allocated',
        'shipped',
        'reference',
        'sale_price',
        'target_date',
    ]

    ordering_field_aliases = {
        'customer': 'order__customer__name',
        'part': 'part__name',
        'order': 'order__reference',
    }

    search_fields = ['part__name', 'quantity', 'reference']


class SalesOrderLineItemDetail(SalesOrderLineItemMixin, RetrieveUpdateDestroyAPI):
    """API endpoint for detail view of a SalesOrderLineItem object."""


class SalesOrderExtraLineList(GeneralExtraLineList, ListCreateAPI):
    """API endpoint for accessing a list of SalesOrderExtraLine objects."""

    queryset = models.SalesOrderExtraLine.objects.all()
    serializer_class = serializers.SalesOrderExtraLineSerializer


class SalesOrderExtraLineDetail(RetrieveUpdateDestroyAPI):
    """API endpoint for detail view of a SalesOrderExtraLine object."""

    queryset = models.SalesOrderExtraLine.objects.all()
    serializer_class = serializers.SalesOrderExtraLineSerializer


class SalesOrderContextMixin:
    """Mixin to add sales order object as serializer context variable."""

    queryset = models.SalesOrder.objects.all()

    def get_serializer_context(self):
        """Add the 'order' reference to the serializer context for any classes which inherit this mixin."""
        ctx = super().get_serializer_context()

        ctx['request'] = self.request

        try:
            ctx['order'] = models.SalesOrder.objects.get(pk=self.kwargs.get('pk', None))
        except Exception:
            pass

        return ctx


class SalesOrderHold(SalesOrderContextMixin, CreateAPI):
    """API endpoint to place a SalesOrder on hold."""

    serializer_class = serializers.SalesOrderHoldSerializer


class SalesOrderCancel(SalesOrderContextMixin, CreateAPI):
    """API endpoint to cancel a SalesOrder."""

    serializer_class = serializers.SalesOrderCancelSerializer


class SalesOrderIssue(SalesOrderContextMixin, CreateAPI):
    """API endpoint to issue a SalesOrder."""

    serializer_class = serializers.SalesOrderIssueSerializer


class SalesOrderComplete(SalesOrderContextMixin, CreateAPI):
    """API endpoint for manually marking a SalesOrder as "complete"."""

    serializer_class = serializers.SalesOrderCompleteSerializer


class SalesOrderAllocateSerials(SalesOrderContextMixin, CreateAPI):
    """API endpoint to allocation stock items against a SalesOrder, by specifying serial numbers."""

    queryset = models.SalesOrder.objects.none()
    serializer_class = serializers.SalesOrderSerialAllocationSerializer


class SalesOrderAllocate(SalesOrderContextMixin, CreateAPI):
    """API endpoint to allocate stock items against a SalesOrder.

    - The SalesOrder is specified in the URL
    - See the SalesOrderShipmentAllocationSerializer class
    """

    queryset = models.SalesOrder.objects.none()
    serializer_class = serializers.SalesOrderShipmentAllocationSerializer


class SalesOrderAllocationFilter(rest_filters.FilterSet):
    """Custom filterset for the SalesOrderAllocationList endpoint."""

    class Meta:
        """Metaclass options."""

        model = models.SalesOrderAllocation
        fields = ['shipment', 'line', 'item']

    order = rest_filters.ModelChoiceFilter(
        queryset=models.SalesOrder.objects.all(),
        field_name='line__order',
        label=_('Order'),
    )

    include_variants = rest_filters.BooleanFilter(
        label=_('Include Variants'), method='filter_include_variants'
    )

    def filter_include_variants(self, queryset, name, value):
        """Filter by whether or not to include variants of the selected part.

        Note:
        - This filter does nothing by itself, and requires the 'part' filter to be set.
        - Refer to the 'filter_part' method for more information.
        """
        return queryset

    part = rest_filters.ModelChoiceFilter(
        queryset=Part.objects.all(), method='filter_part', label=_('Part')
    )

    @extend_schema_field(rest_framework.serializers.IntegerField(help_text=_('Part')))
    def filter_part(self, queryset, name, part):
        """Filter by the 'part' attribute.

        Note:
        - If "include_variants" is True, include all variants of the selected part
        - Otherwise, just filter by the selected part
        """
        include_variants = str2bool(self.data.get('include_variants', False))

        if include_variants:
            parts = part.get_descendants(include_self=True)
            return queryset.filter(item__part__in=parts)
        else:
            return queryset.filter(item__part=part)

    outstanding = rest_filters.BooleanFilter(
        label=_('Outstanding'), method='filter_outstanding'
    )

    def filter_outstanding(self, queryset, name, value):
        """Filter by "outstanding" status (boolean)."""
        if str2bool(value):
            return queryset.filter(
                line__order__status__in=SalesOrderStatusGroups.OPEN,
                shipment__shipment_date=None,
            )
        return queryset.exclude(
            shipment__shipment_date=None,
            line__order__status__in=SalesOrderStatusGroups.OPEN,
        )

    assigned_to_shipment = rest_filters.BooleanFilter(
        label=_('Has Shipment'), method='filter_assigned_to_shipment'
    )

    def filter_assigned_to_shipment(self, queryset, name, value):
        """Filter by whether or not the allocation has been assigned to a shipment."""
        if str2bool(value):
            return queryset.exclude(shipment=None)
        return queryset.filter(shipment=None)

    location = rest_filters.ModelChoiceFilter(
        queryset=stock_models.StockLocation.objects.all(),
        label=_('Location'),
        method='filter_location',
    )

    @extend_schema_field(
        rest_framework.serializers.IntegerField(help_text=_('Location'))
    )
    def filter_location(self, queryset, name, location):
        """Filter by the location of the allocated StockItem."""
        locations = location.get_descendants(include_self=True)
        return queryset.filter(item__location__in=locations)


class SalesOrderAllocationMixin:
    """Mixin class for SalesOrderAllocation endpoints."""

    queryset = models.SalesOrderAllocation.objects.all()
    serializer_class = serializers.SalesOrderAllocationSerializer

    def get_queryset(self, *args, **kwargs):
        """Annotate the queryset for this endpoint."""
        queryset = super().get_queryset(*args, **kwargs)

        queryset = queryset.prefetch_related(
            'item',
            'item__sales_order',
            'item__part',
            'line__part',
            'item__location',
            'line__order',
            'line__order__responsible',
            'line__order__project_code',
            'line__order__project_code__responsible',
            'shipment',
            'shipment__order',
            'shipment__checked_by',
        ).select_related('line__part__pricing_data', 'item__part__pricing_data')

        return queryset


class SalesOrderAllocationList(SalesOrderAllocationMixin, BulkUpdateMixin, ListAPI):
    """API endpoint for listing SalesOrderAllocation objects."""

    filterset_class = SalesOrderAllocationFilter
    filter_backends = SEARCH_ORDER_FILTER_ALIAS

    ordering_fields = [
        'quantity',
        'part',
        'serial',
        'IPN',
        'batch',
        'location',
        'order',
        'shipment_date',
    ]

    ordering_field_aliases = {
        'IPN': 'item__part__IPN',
        'part': 'item__part__name',
        'serial': ['item__serial_int', 'item__serial'],
        'batch': 'item__batch',
        'location': 'item__location__name',
        'order': 'line__order__reference',
        'shipment_date': 'shipment__shipment_date',
    }

    search_fields = {
        'item__part__name',
        'item__part__IPN',
        'item__serial',
        'item__batch',
    }

    def get_serializer(self, *args, **kwargs):
        """Return the serializer instance for this endpoint.

        Adds extra detail serializers if requested
        """
        try:
            params = self.request.query_params

            kwargs['part_detail'] = str2bool(params.get('part_detail', False))
            kwargs['item_detail'] = str2bool(params.get('item_detail', False))
            kwargs['order_detail'] = str2bool(params.get('order_detail', False))
            kwargs['location_detail'] = str2bool(params.get('location_detail', False))
            kwargs['customer_detail'] = str2bool(params.get('customer_detail', False))
        except AttributeError:
            pass

        return super().get_serializer(*args, **kwargs)


class SalesOrderAllocationDetail(SalesOrderAllocationMixin, RetrieveUpdateDestroyAPI):
    """API endpoint for detali view of a SalesOrderAllocation object."""


class SalesOrderShipmentFilter(rest_filters.FilterSet):
    """Custom filterset for the SalesOrderShipmentList endpoint."""

    class Meta:
        """Metaclass options."""

        model = models.SalesOrderShipment
        fields = ['order']

    shipped = rest_filters.BooleanFilter(label='shipped', method='filter_shipped')

    def filter_shipped(self, queryset, name, value):
        """Filter SalesOrder list by 'shipped' status (boolean)."""
        if str2bool(value):
            return queryset.exclude(shipment_date=None)
        return queryset.filter(shipment_date=None)

    delivered = rest_filters.BooleanFilter(label='delivered', method='filter_delivered')

    def filter_delivered(self, queryset, name, value):
        """Filter SalesOrder list by 'delivered' status (boolean)."""
        if str2bool(value):
            return queryset.exclude(delivery_date=None)
        return queryset.filter(delivery_date=None)


class SalesOrderShipmentMixin:
    """Mixin class for SalesOrderShipment endpoints."""

    queryset = models.SalesOrderShipment.objects.all()
    serializer_class = serializers.SalesOrderShipmentSerializer

    def get_queryset(self, *args, **kwargs):
        """Return annotated queryset for this endpoint."""
        queryset = super().get_queryset(*args, **kwargs)

        queryset = serializers.SalesOrderShipmentSerializer.annotate_queryset(queryset)

        # Debug print
        print("SalesOrderShipmentMixin.get_queryset ->", queryset.query)

        return queryset

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from order.models import SalesOrderAllocation
import json

class SalesOrderShipmentList(SalesOrderShipmentMixin, ListCreateAPI):
    """API list endpoint for SalesOrderShipment model."""

    filterset_class = SalesOrderShipmentFilter
    filter_backends = SEARCH_ORDER_FILTER_ALIAS
    ordering_fields = ['reference', 'delivery_date', 'shipment_date', 'allocated_items']

    search_fields = [ 
        'order__reference',
        'reference',
        'tracking_number',
        'invoice_number',
    ]

    def list(self, request, *args, **kwargs):
        print("🔎 GET List request params:", request.query_params)
        response = super().list(request, *args, **kwargs)
        print("✅ GET List response:", response.data)
        return response

    def create(self, request, *args, **kwargs): 
        print("🟡 Data being submitted:", request.data)

        # Proceed with creation
        response = super().create(request, *args, **kwargs)
        print("✅ Shipment created with response:", response.data)

        if hasattr(response, 'status_code') and response.status_code == 400:
            print("❌ Serializer errors:", getattr(response, 'data', 'No data'))
            return response

        send_email = request.data.get('send_email', False)
        print("📩 Send email flag:", send_email)

        if str(send_email).lower() == 'true':
            try:
                shipment_pk = response.data.get('pk')
                print(f"🔍 Fetching shipment with pk={shipment_pk}")
                shipment = self.get_queryset().filter(pk=shipment_pk).first()

                if shipment:
                    print(f"✅ Shipment found: reference={shipment.reference}, order_id={shipment.order.id}")
                    order = shipment.order
                    customer = order.customer
                    print(f"👤 Customer: name={customer.name}, email={customer.email}")

                    alloc_items = SalesOrderAllocation.objects.filter(line__order=order)
                    print(f"📦 Allocated items found: {alloc_items.count()}")
                    for a in alloc_items:
                        print(f" - Allocation ID={a.pk}, Part={a.item.part.name}, Qty={a.quantity}, Sale Price={a.line.sale_price}")

                    if not alloc_items.exists():
                        print("⚠️ No allocations linked to this order. Skipping email.")
                        return response

                    # Build email data
                    email_data = {
                        'name': customer.name or customer.individual_name,
                        'email': customer.email,
                        'tracking_number': shipment.tracking_number,
                        'order_id': order.pk,
                        'courier_company_detail': {
                            'name': shipment.courier_company.company_name,
                            'website': shipment.courier_company.website,
                            'tracking_link': shipment.courier_company.tracking_link,
                        },
                        'part_details': [ 
                            {
                                'quantity': float(item.quantity),
                                'sale_price': float(item.line.sale_price.amount) if hasattr(item.line.sale_price, 'amount') else float(item.line.sale_price),
                                'part_detail': {
                                    'name': item.item.part.name,
                                    'description': item.item.part.description,
                                    'image': item.item.part.image.url if item.item.part.image else '',
                                }
                            }
                            for item in alloc_items
                        ]
                    }

                    print("📧 Prepared email payload:")
                    print(json.dumps(email_data, indent=2))

                    class FakeRequest:
                        method = 'POST'
                        body = json.dumps(email_data).encode('utf-8')

                    send_response = send_shipment_email(FakeRequest())
                    print("✅ Email send response:", send_response.content)
                else:
                    print("❌ [WARNING] Shipment not found after creation")

            except Exception as e:
                print("❌ [EMAIL ERROR]", str(e))

        return response

    
from order.models import SalesOrderAllocation
import json

class SalesOrderShipmentDetail(SalesOrderShipmentMixin, RetrieveUpdateDestroyAPI):
    """API detail endpoint for SalesOrderShipment model."""

    def retrieve(self, request, *args, **kwargs):
        print("🔎 GET Detail request params:", request.query_params)
        response = super().retrieve(request, *args, **kwargs)
        print("✅ GET Detail response:", response.data)
        return response

    def update(self, request, *args, **kwargs):
        print("🟡 Data being updated:", request.data)

        # Proceed with update
        response = super().update(request, *args, **kwargs)
        print("✅ Shipment updated with response:", response.data)

        if hasattr(response, 'status_code') and response.status_code == 400:
            print("❌ Serializer errors:", getattr(response, 'data', 'No data'))
            return response

        send_email = request.data.get('send_email', False) 
        print("📩 Send email flag:", send_email)

        if str(send_email).lower() == 'true':
            try:
                shipment_pk = response.data.get('pk')
                print(f"🔍 Fetching shipment with pk={shipment_pk}")
                shipment = self.get_queryset().filter(pk=shipment_pk).first()

                if shipment:
                    print(f"✅ Shipment found: reference={shipment.reference}, order_id={shipment.order.id}")
                    order = shipment.order
                    customer = order.customer
                    print(f"👤 Customer: name={customer.name}, email={customer.email}")

                    alloc_items = SalesOrderAllocation.objects.filter(line__order=order)
                    print(f"📦 Allocated items found: {alloc_items.count()}")
                    for a in alloc_items:
                        print(f" - Allocation ID={a.pk}, Part={a.item.part.name}, Qty={a.quantity}, Sale Price={a.line.sale_price}")

                    if not alloc_items.exists():
                        print("⚠️ No allocations linked to this order. Skipping email.")
                        return response

                    # Build email data
                    email_data = {
                        'name': customer.name or customer.individual_name,
                        'email': customer.email,
                        'tracking_number': shipment.tracking_number,
                        'order_id': order.pk,
                        'courier_company_detail': {
                            'name': shipment.courier_company.company_name,
                            'website': shipment.courier_company.website,
                            'tracking_link': shipment.courier_company.tracking_link,
                        },
                        'part_details': [
                            {
                                'quantity': float(item.quantity),
                                'sale_price': float(item.line.sale_price.amount) if hasattr(item.line.sale_price, 'amount') else float(item.line.sale_price),
                                'part_detail': {
                                    'name': item.item.part.name,
                                    'description': item.item.part.description,
                                    'image': item.item.part.image.url if item.item.part.image else '',
                                }
                            }
                            for item in alloc_items
                        ]
                    }

                    print("📧 Prepared email payload:")
                    print(json.dumps(email_data, indent=2))

                    class FakeRequest:
                        method = 'POST'
                        body = json.dumps(email_data).encode('utf-8')

                    send_response = send_shipment_email(FakeRequest())
                    print("✅ Email send response:", send_response.content)
                else:
                    print("❌ [WARNING] Shipment not found after update")

            except Exception as e:
                print("❌ [EMAIL ERROR]", str(e))

        return response


class SalesOrderShipmentComplete(CreateAPI):
    """API endpoint for completing (shipping) a SalesOrderShipment."""

    queryset = models.SalesOrderShipment.objects.all()
    serializer_class = serializers.SalesOrderShipmentCompleteSerializer

    def get_serializer_context(self):
        """Pass the request object to the serializer."""
        ctx = super().get_serializer_context()
        ctx['request'] = self.request

        try:
            ctx['shipment'] = models.SalesOrderShipment.objects.get(
                pk=self.kwargs.get('pk', None)
            )
        except Exception:
            pass

        return ctx


class ReturnOrderFilter(OrderFilter):
    """Custom API filters for the ReturnOrderList endpoint."""

    class Meta:
        """Metaclass options."""

        model = models.ReturnOrder
        fields = ['customer']

    include_variants = rest_filters.BooleanFilter(
        label=_('Include Variants'), method='filter_include_variants'
    )

    def filter_include_variants(self, queryset, name, value):
        """Filter by whether or not to include variants of the selected part.

        Note:
        - This filter does nothing by itself, and requires the 'part' filter to be set.
        - Refer to the 'filter_part' method for more information.
        """
        return queryset

    part = rest_filters.ModelChoiceFilter(
        queryset=Part.objects.all(), field_name='part', method='filter_part'
    )

    @extend_schema_field(OpenApiTypes.INT)
    def filter_part(self, queryset, name, part):
        """Filter by selected 'part'.

        Note:
        - If 'include_variants' is set to True, then all variants of the selected part will be included.
        - Otherwise, just filter by the selected part.
        """
        include_variants = str2bool(self.data.get('include_variants', False))

        if include_variants:
            parts = part.get_descendants(include_self=True)
        else:
            parts = Part.objects.filter(pk=part.pk)

        # Now that we have a queryset of parts, find all the matching return orders
        line_items = models.ReturnOrderLineItem.objects.filter(item__part__in=parts)

        # Generate a list of ID values for the matching return orders
        return_orders = line_items.values_list('order', flat=True).distinct()

        # Now we have a list of matching IDs, filter the queryset
        return queryset.filter(pk__in=return_orders)

    completed_before = InvenTreeDateFilter(
        label=_('Completed Before'), field_name='complete_date', lookup_expr='lt'
    )

    completed_after = InvenTreeDateFilter(
        label=_('Completed After'), field_name='complete_date', lookup_expr='gt'
    )


class ReturnOrderMixin:
    """Mixin class for ReturnOrder endpoints."""

    queryset = models.ReturnOrder.objects.all()
    serializer_class = serializers.ReturnOrderSerializer

    def get_serializer(self, *args, **kwargs):
        """Return serializer instance for this endpoint."""
        try:
            kwargs['customer_detail'] = str2bool(
                self.request.query_params.get('customer_detail', False)
            )
        except AttributeError:
            pass

        # Ensure the context is passed through to the serializer
        kwargs['context'] = self.get_serializer_context()

        return super().get_serializer(*args, **kwargs)

    def get_queryset(self, *args, **kwargs):
        """Return annotated queryset for this endpoint."""
        queryset = super().get_queryset(*args, **kwargs)

        queryset = queryset.prefetch_related(
            'customer', 'lines', 'project_code', 'responsible'
        )

        queryset = serializers.ReturnOrderSerializer.annotate_queryset(queryset)

        return queryset


class ReturnOrderList(
    ReturnOrderMixin, OrderCreateMixin, DataExportViewMixin, ListCreateAPI
):
    """API endpoint for accessing a list of ReturnOrder objects."""

    filterset_class = ReturnOrderFilter

    filter_backends = SEARCH_ORDER_FILTER_ALIAS

    ordering_field_aliases = {
        'reference': ['reference_int', 'reference'],
        'project_code': ['project_code__code'],
    }

    ordering_fields = [
        'creation_date',
        'created_by',
        'reference',
        'customer__name',
        'customer_reference',
        'line_items',
        'status',
        'start_date',
        'target_date',
        'complete_date',
        'project_code',
    ]

    search_fields = [
        'customer__name',
        'reference',
        'description',
        'customer_reference',
        'project_code__code',
    ]

    ordering = '-reference'


class ReturnOrderDetail(ReturnOrderMixin, RetrieveUpdateDestroyAPI):
    """API endpoint for detail view of a single ReturnOrder object."""


class ReturnOrderContextMixin:
    """Simple mixin class to add a ReturnOrder to the serializer context."""

    queryset = models.ReturnOrder.objects.all()

    def get_serializer_context(self):
        """Add the PurchaseOrder object to the serializer context."""
        context = super().get_serializer_context()

        # Pass the ReturnOrder instance through to the serializer for validation
        try:
            context['order'] = models.ReturnOrder.objects.get(
                pk=self.kwargs.get('pk', None)
            )
        except Exception:
            pass

        context['request'] = self.request

        return context


class ReturnOrderCancel(ReturnOrderContextMixin, CreateAPI):
    """API endpoint to cancel a ReturnOrder."""

    serializer_class = serializers.ReturnOrderCancelSerializer


class ReturnOrderHold(ReturnOrderContextMixin, CreateAPI):
    """API endpoint to hold a ReturnOrder."""

    serializer_class = serializers.ReturnOrderHoldSerializer


class ReturnOrderComplete(ReturnOrderContextMixin, CreateAPI):
    """API endpoint to complete a ReturnOrder."""

    serializer_class = serializers.ReturnOrderCompleteSerializer


class ReturnOrderIssue(ReturnOrderContextMixin, CreateAPI):
    """API endpoint to issue (place) a ReturnOrder."""

    serializer_class = serializers.ReturnOrderIssueSerializer


class ReturnOrderReceive(ReturnOrderContextMixin, CreateAPI):
    """API endpoint to receive items against a ReturnOrder."""

    queryset = models.ReturnOrder.objects.none()
    serializer_class = serializers.ReturnOrderReceiveSerializer


class ReturnOrderLineItemFilter(LineItemFilter):
    """Custom filters for the ReturnOrderLineItemList endpoint."""

    class Meta:
        """Metaclass options."""

        price_field = 'price'
        model = models.ReturnOrderLineItem
        fields = ['order', 'item']

    outcome = rest_filters.NumberFilter(label='outcome')

    received = rest_filters.BooleanFilter(label='received', method='filter_received')

    def filter_received(self, queryset, name, value):
        """Filter by 'received' field."""
        if str2bool(value):
            return queryset.exclude(received_date=None)
        return queryset.filter(received_date=None)


class ReturnOrderLineItemMixin:
    """Mixin class for ReturnOrderLineItem endpoints."""

    queryset = models.ReturnOrderLineItem.objects.all()
    serializer_class = serializers.ReturnOrderLineItemSerializer

    def get_serializer(self, *args, **kwargs):
        """Return serializer for this endpoint with extra data as requested."""
        try:
            params = self.request.query_params

            kwargs['order_detail'] = str2bool(params.get('order_detail', False))
            kwargs['item_detail'] = str2bool(params.get('item_detail', True))
            kwargs['part_detail'] = str2bool(params.get('part_detail', False))
        except AttributeError:
            pass

        kwargs['context'] = self.get_serializer_context()

        return super().get_serializer(*args, **kwargs)

    def get_queryset(self, *args, **kwargs):
        """Return annotated queryset for this endpoint."""
        queryset = super().get_queryset(*args, **kwargs)

        queryset = queryset.prefetch_related('order', 'item', 'item__part')

        return queryset


class ReturnOrderLineItemList(
    ReturnOrderLineItemMixin, DataExportViewMixin, ListCreateAPI
):
    """API endpoint for accessing a list of ReturnOrderLineItemList objects."""

    filterset_class = ReturnOrderLineItemFilter

    filter_backends = SEARCH_ORDER_FILTER

    ordering_fields = ['reference', 'target_date', 'received_date']

    search_fields = [
        'item_serial',
        'item__part__name',
        'item__part__description',
        'reference',
    ]


class ReturnOrderLineItemDetail(ReturnOrderLineItemMixin, RetrieveUpdateDestroyAPI):
    """API endpoint for detail view of a ReturnOrderLineItem object."""


class ReturnOrderExtraLineList(GeneralExtraLineList, ListCreateAPI):
    """API endpoint for accessing a list of ReturnOrderExtraLine objects."""

    queryset = models.ReturnOrderExtraLine.objects.all()
    serializer_class = serializers.ReturnOrderExtraLineSerializer


class ReturnOrderExtraLineDetail(RetrieveUpdateDestroyAPI):
    """API endpoint for detail view of a ReturnOrderExtraLine object."""

    queryset = models.ReturnOrderExtraLine.objects.all()
    serializer_class = serializers.ReturnOrderExtraLineSerializer


class OrderCalendarExport(ICalFeed):
    """Calendar export for Purchase/Sales Orders.

    Optional parameters:
    - include_completed: true/false
        whether or not to show completed orders. Defaults to false
    """

    instance_url = get_base_url()

    instance_url = instance_url.replace('http://', '').replace('https://', '')
    timezone = settings.TIME_ZONE
    file_name = 'calendar.ics'

    def __call__(self, request, *args, **kwargs):
        """Overload call in order to check for authentication.

        This is required to force Django to look for the authentication,
        otherwise login request with Basic auth via curl or similar are ignored,
        and login via a calendar client will not work.

        See:
        https://stackoverflow.com/questions/3817694/django-rss-feed-authentication
        https://stackoverflow.com/questions/152248/can-i-use-http-basic-authentication-with-django
        https://www.djangosnippets.org/snippets/243/
        """
        import base64

        if request.user.is_authenticated:
            # Authenticated on first try - maybe normal browser call?
            return super().__call__(request, *args, **kwargs)

        # No login yet - check in headers
        if 'authorization' in request.headers:
            auth = request.headers['authorization'].split()
            if len(auth) == 2:
                # NOTE: We are only support basic authentication for now.
                #
                if auth[0].lower() == 'basic':
                    uname, passwd = base64.b64decode(auth[1]).decode('ascii').split(':')
                    user = authenticate(username=uname, password=passwd)
                    if user is not None and user.is_active:
                        login(request, user)
                        request.user = user

        # Check again
        if request.user.is_authenticated:
            # Authenticated after second try
            return super().__call__(request, *args, **kwargs)

        # Still nothing - return Unauth. header with info on how to authenticate
        # Information is needed by client, eg Thunderbird
        response = JsonResponse({
            'detail': 'Authentication credentials were not provided.'
        })
        response['WWW-Authenticate'] = 'Basic realm="api"'
        response.status_code = 401
        return response

    def get_object(self, request, *args, **kwargs):
        """This is where settings from the URL etc will be obtained."""
        # Help:
        # https://django.readthedocs.io/en/stable/ref/contrib/syndication.html

        obj = {}
        obj['ordertype'] = kwargs['ordertype']
        obj['include_completed'] = bool(request.GET.get('include_completed', False))

        return obj

    def title(self, obj):
        """Return calendar title."""
        if obj['ordertype'] == 'purchase-order':
            ordertype_title = _('Purchase Order')
        elif obj['ordertype'] == 'sales-order':
            ordertype_title = _('Sales Order')
        elif obj['ordertype'] == 'return-order':
            ordertype_title = _('Return Order')
        else:
            ordertype_title = _('Unknown')

        company_name = common.settings.get_global_setting('INVENTREE_COMPANY_NAME')

        return f'{company_name} {ordertype_title}'

    def product_id(self, obj):
        """Return calendar product id."""
        return f'//{self.instance_url}//{self.title(obj)}//EN'

    def items(self, obj):
        """Return a list of Orders.

        Filters:
        - Only return those which have a target_date set
        - Only return incomplete orders, unless include_completed is set to True
        """
        if obj['ordertype'] == 'purchase-order':
            if obj['include_completed'] is False:
                # Do not include completed orders from list in this case
                # Completed status = 30
                outlist = models.PurchaseOrder.objects.filter(
                    target_date__isnull=False
                ).filter(status__lt=PurchaseOrderStatus.COMPLETE.value)
            else:
                outlist = models.PurchaseOrder.objects.filter(target_date__isnull=False)
        elif obj['ordertype'] == 'sales-order':
            if obj['include_completed'] is False:
                # Do not include completed (=shipped) orders from list in this case
                # Shipped status = 20
                outlist = models.SalesOrder.objects.filter(
                    target_date__isnull=False
                ).filter(status__lt=SalesOrderStatus.SHIPPED.value)
            else:
                outlist = models.SalesOrder.objects.filter(target_date__isnull=False)
        elif obj['ordertype'] == 'return-order':
            if obj['include_completed'] is False:
                # Do not include completed orders from list in this case
                # Complete status = 30
                outlist = models.ReturnOrder.objects.filter(
                    target_date__isnull=False
                ).filter(status__lt=ReturnOrderStatus.COMPLETE.value)
            else:
                outlist = models.ReturnOrder.objects.filter(target_date__isnull=False)
        else:
            outlist = []

        return outlist

    def item_title(self, item):
        """Set the event title to the order reference."""
        return f'{item.reference}'

    def item_description(self, item):
        """Set the event description."""
        return f'Company: {item.company.name}\nStatus: {item.get_status_display()}\nDescription: {item.description}'

    def item_start_datetime(self, item):
        """Set event start to target date. Goal is all-day event."""
        return item.target_date

    def item_end_datetime(self, item):
        """Set event end to target date. Goal is all-day event."""
        return item.target_date

    def item_created(self, item):
        """Use creation date of PO as creation date of event."""
        return item.creation_date

    def item_class(self, item):
        """Set item class to PUBLIC."""
        return 'PUBLIC'

    def item_guid(self, item):
        """Return globally unique UID for event."""
        return f'po_{item.pk}_{item.reference.replace(" ", "-")}@{self.instance_url}'

    def item_link(self, item):
        """Set the item link."""
        return construct_absolute_url(item.get_absolute_url())
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated  # If you need only authenticated users
from .models import CourierCompany  # Import the CourierCompany model
from .serializers import CourierCompanySerializer  # Import the CourierCompany serializer
from rest_framework.response import Response

# If you need a more specific permission class
from rest_framework.permissions import DjangoModelPermissionsOrAnonReadOnly  # Optional, to allow public read-only access

class CourierCompanyViewSet(viewsets.ModelViewSet):
    queryset = CourierCompany.objects.all()
    serializer_class = CourierCompanySerializer
    # If you want to restrict access to only authenticated users, use IsAuthenticated
    permission_classes = [IsAuthenticated]  # Change as needed
    # permission_classes = [DjangoModelPermissionsOrAnonReadOnly]  # Optional if public read access is allowed

    def list(self, request, *args, **kwargs):
        """
        Optionally, you can override list, retrieve, or create methods to add custom logic.
        This is useful if you want to filter the queryset or add logging, etc.
        """
        return super().list(request, *args, **kwargs)




# stdlib
from pathlib import Path

# 3rd-party
from django.http import FileResponse, Http404, HttpResponseForbidden
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request

# local
from . import models         # SalesOrder model lives here


def _bool(val: str | None) -> bool:
    """Interpret '1', 'true', 'yes' (case-insensitive) as True."""
    return str(val).lower() in ("1", "true", "yes")


class SalesOrderShippingLabel(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk, *args, **kwargs):
        # 1) Fetch or 404
        try:
            order = models.SalesOrder.objects.get(pk=pk)
        except models.SalesOrder.DoesNotExist:
            raise Http404("SalesOrder not found")

        # 2) Always rebuild the label
        order.generate_shipping_label(overwrite=True)

        # 3) Stream it back
        fh = order.shipping_label.open("rb")
        filename = f"SO_{order.reference}_label.pdf"
        response = FileResponse(
            fh,
            as_attachment=True,
            filename=filename,
            content_type="application/pdf",
        )

        # 4) Disable caching
        response["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response["Pragma"] = "no-cache"
        response["Expires"] = "0"

        return response

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.http import FileResponse
from io import BytesIO
from PyPDF2 import PdfMerger
from django.core.cache import cache
import uuid
import threading
import os
from . import models

class SalesOrderBatchShippingLabelStart(APIView):
    """
    Start label + invoice generation in background and return task_id.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        order_ids = request.data.get("order_ids", [])
        if not order_ids:
            return Response({"error": "No order IDs provided"}, status=400)

        task_id = str(uuid.uuid4())
        cache.set(task_id, {
            "status": "started",
            "progress": 0,
            "total": len(order_ids)
        }, timeout=3600)

        # Run generation in background
        threading.Thread(
            target=self._generate_pdfs,
            args=(task_id, order_ids),
            daemon=True
        ).start()

        return Response({
            "task_id": task_id,
            "message": "Label and invoice generation started."
        })

    def _generate_pdfs(self, task_id, order_ids):
        label_merger = PdfMerger()
        invoice_merger = PdfMerger()

        total = len(order_ids)
        failed_orders = []

        for i, pk in enumerate(order_ids, start=1):
            try:
                order = models.SalesOrder.objects.get(pk=pk)
                print(f"Processing order {order.pk}...")

                # --------------------------
                # 1️⃣ Generate and merge label
                # --------------------------
                order.generate_shipping_label(overwrite=True)
                if order.shipping_label:
                    with order.shipping_label.open("rb") as fh:
                        label_merger.append(fh)
                else:
                    print(f"[WARN] Missing label for order {pk}")
                    failed_orders.append(pk)

                # --------------------------
                # 2️⃣ Merge invoices
                # --------------------------
                shipments = models.SalesOrderShipment.objects.filter(order=order)
                for shipment in shipments:
                    invoice_number = getattr(shipment, "invoice_number", None)
                    if not invoice_number:
                        continue

                    # zoho_pdf = download_zoho_invoice_pdf(invoice_number)
                    # if zoho_pdf:
                    #     # ✅ directly append the BytesIO object
                    #     invoice_merger.append(zoho_pdf)
                    #     print(f"[ZOHO] Added invoice {invoice_number} for order {order.pk}")
                    # else:
                    #     print(f"[ZOHO] Failed to fetch invoice {invoice_number} for order {order.pk}")

            except Exception as e:
                print(f"[ERROR] Failed processing order {pk}: {e}")
                failed_orders.append(pk)

            # --------------------------
            # 3️⃣ Update cache progress
            # --------------------------
            cache.set(task_id, {
                "status": "in-progress",
                "progress": i,
                "total": total,
                "failed": failed_orders,
            }, timeout=3600)

        # --------------------------
        # 4️⃣ Write output PDFs
        # --------------------------
        label_path = f"/tmp/labels_{task_id}.pdf"
        invoice_path = f"/tmp/invoices_{task_id}.pdf"

        try:
            if len(label_merger.pages) > 0:
                with open(label_path, "wb") as f:
                    label_merger.write(f)
            label_merger.close()

            if len(invoice_merger.pages) > 0:
                with open(invoice_path, "wb") as f:
                    invoice_merger.write(f)
            invoice_merger.close()
        except Exception as e:
            print(f"[ERROR] Writing merged PDFs: {e}")

        # --------------------------
        # 5️⃣ Update final cache status
        # --------------------------
        cache.set(task_id, {
            "status": "ready",
            "progress": total,
            "total": total,
            "failed": failed_orders,
            "label_download_url": f"/api/order/so/batch-shipping-label-download/{task_id}/",
            # "invoice_download_url": f"/api/order/so/batch-invoice-download/{task_id}/"
        }, timeout=3600)


class SalesOrderBatchShippingLabelProgress(APIView):
    """Check label/invoice generation progress"""
    permission_classes = [IsAuthenticated]

    def get(self, request, task_id):
        data = cache.get(task_id)
        if not data:
            return Response({"error": "Invalid or expired task ID"}, status=404)
        return Response(data)


class SalesOrderBatchShippingLabelDownload(APIView):
    """Download the final merged label PDF"""
    permission_classes = [IsAuthenticated]

    def get(self, request, task_id):
        pdf_path = f"/tmp/labels_{task_id}.pdf"
        try:
            return FileResponse(open(pdf_path, "rb"), as_attachment=True, filename=f"ShippingLabels_{task_id}.pdf")
        except FileNotFoundError:
            return Response({"error": "Label file not found"}, status=404)


class SalesOrderBatchInvoiceDownload(APIView):
    """Download the final merged invoice PDF"""
    permission_classes = [IsAuthenticated]

    def get(self, request, task_id):
        pdf_path = f"/tmp/invoices_{task_id}.pdf"
        try:
            return FileResponse(open(pdf_path, "rb"), as_attachment=True, filename=f"Invoices_{task_id}.pdf")
        except FileNotFoundError:
            return Response({"error": "Invoice file not found"}, status=404)


 
# order/api.py  – put this near the top of the file
# ───────────────────────── imports ─────────────────────────
import io
from datetime import date
from pathlib import Path

from django.conf import settings
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from reportlab.lib import colors
from PIL import Image
import qrcode
from barcode import Code128
from barcode.writer import ImageWriter

# ─────────────────── asset helpers ────────────────────────
ASSET_DIR = Path(settings.BASE_DIR) / "label_assets"      # change if needed

def load_pil(name: str) -> Image.Image:
    """Return a PIL.Image loaded from *label_assets/name*."""
    return Image.open(ASSET_DIR / name)                   # will raise FileNotFoundError if missing

def asset_path(name: str) -> str:
    """Return absolute path string for an asset (useful for logo)."""
    return str(ASSET_DIR / name)

def build_sales_order_label(order) -> str:
    """
    Build a 10 cm × 10 cm PDF shipping label and return relative media path.
    The function *only* feeds PIL.Image objects or file-paths to ReportLab.
    """
    from datetime import date
    from barcode import Code128
    from barcode.writer import ImageWriter

    # ---------- customer & address ------------------------
    cust   = getattr(order, "customer", None)
    is_obj = hasattr(cust, "primary_address")
    print(f"Customer: {cust}")

    person  = cust.individual_name if is_obj else ""
    company = (cust.name ) if is_obj else (cust or order.customer_name)

    addr = getattr(order, "shipping_address", None) or (cust.primary_address if is_obj else None)
    if addr:
        country = getattr(addr.country, "name", str(addr.country))
        addr_lines = [
            person,
            company,
            addr.line1,
            addr.line2 or "",
            f"{addr.postal_code} {addr.postal_city}".strip(),
            country,
        ]
    else:
        addr_lines = [person, company, "(No address on file)"]
        
    # ---------- phone & email -----------------------------
    def first_nonempty(*vals):
        return next((v for v in vals if v), "")

    contact = getattr(order, "contact", None)

    phone_raw = first_nonempty(
        getattr(contact, "phone", None) if contact else None,
        getattr(cust, "phone", None),
        getattr(addr, "phone", None),
    )
    email_raw = first_nonempty(
        getattr(contact, "email", None) if contact else None,
        getattr(cust, "email", None),
        getattr(addr, "email", None),
    )

    phone = phone_raw.strip() if phone_raw else ""
    email = email_raw.strip().lower() if email_raw else ""

    if phone:
        addr_lines.append(f"Phone: {phone}")
    if email:
        addr_lines.append(f"Email: {email}")

    # ---------- images ------------------------------------
    qr = qrcode.QRCode(
        version=2,
        box_size=10,
        border=1
    )
    qr.add_data(order.reference)
    qr.make(fit=True)
    barcode_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    logo_path   = asset_path("Vicharak Favicon_Black On White.png")           # file path string
    qr_tiles = [
        (load_pil("vicharak.png"),  "Website"),
        (load_pil("discord.png"),  "Discord"),
        (load_pil("store.png"),    "Store"),
    ]

    # ---------- Get the correct shipment date -------------
    shipment_date = None
    
    print(f"Debug - Order status: {getattr(order, 'status', 'Unknown')}")
    print(f"Debug - Order has shipments attr: {hasattr(order, 'shipments')}")
    
    if hasattr(order, "shipments"):
        try:
            print(f"Debug - Attempting to access shipments.all()")
            shipments = order.shipments.all()
            print(f"Debug - Found {len(shipments)} shipments")
            
            for shipment in shipments:
                print(f"Debug - Checking shipment: {shipment.id if hasattr(shipment, 'id') else 'Unknown ID'}")
                
                possible_date_fields = ['date', 'shipment_date', 'completed_date', 'created_date', 'creation_date']
                print(f"Debug - Shipment attributes: {dir(shipment)}")
                
                for field_name in possible_date_fields:
                    if hasattr(shipment, field_name) and getattr(shipment, field_name):
                        date_value = getattr(shipment, field_name)
                        print(f"Debug - Found date in field '{field_name}': {date_value}")
                        shipment_date = date_value
                        break
                
                if shipment_date:
                    break
                    
        except Exception as e:
            print(f"Debug - Error accessing shipments: {e}")
    
    if not shipment_date:
        try:
            print("Debug - Trying to access shipment_date through order.completed_shipments")
            if hasattr(order, "completed_shipments") and order.completed_shipments:
                for shipment in order.completed_shipments.all():
                    if hasattr(shipment, "date") and shipment.date:
                        print(f"Debug - Found date in completed_shipments: {shipment.date}")
                        shipment_date = shipment.date
                        break
        except Exception as e:
            print(f"Debug - Error accessing completed_shipments: {e}")
    
    if not shipment_date and hasattr(order, "shipment_date") and order.shipment_date:
        print(f"Debug - Using order.shipment_date: {order.shipment_date}")
        shipment_date = order.shipment_date
    
    if not shipment_date:
        print("Debug - No shipment date found, using today's date")
        shipment_date = date.today()
        print(f"Debug - Today's date: {shipment_date}")
    
    print(f"Debug - Final shipment date: {shipment_date}")

    # ---------- Get tracking number and invoice number from shipment -------------
    tracking_number = ""
    invoice_number = ""
    tracking_barcode_img = None
    
    if hasattr(order, "shipments"):
        try:
            shipments = order.shipments.all()
            if shipments:
                # Get the first shipment (or you can filter for a specific one)
                shipment = shipments[0]
                
                # Try to get tracking number from various possible field names
                tracking_fields = ['tracking_number', 'tracking', 'tracking_code', 'carrier_tracking']
                for field_name in tracking_fields:
                    if hasattr(shipment, field_name):
                        tracking_value = getattr(shipment, field_name)
                        if tracking_value:
                            tracking_number = str(tracking_value)
                            print(f"Debug - Found tracking number: {tracking_number}")
                            break
                
                # Try to get invoice number from various possible field names
                invoice_fields = ['invoice_number', 'invoice', 'invoice_reference', 'invoice_id']
                for field_name in invoice_fields:
                    if hasattr(shipment, field_name):
                        invoice_value = getattr(shipment, field_name)
                        if invoice_value:
                            invoice_number = str(invoice_value)
                            print(f"Debug - Found invoice number: {invoice_number}")
                            break
                
                # Alternative: Check if shipment has a related invoice object
                if not invoice_number and hasattr(shipment, 'invoice') and shipment.invoice:
                    if hasattr(shipment.invoice, 'number'):
                        invoice_number = str(shipment.invoice.number)
                    elif hasattr(shipment.invoice, 'reference'):
                        invoice_number = str(shipment.invoice.reference)
                        
        except Exception as e:
            print(f"Debug - Error getting tracking/invoice numbers: {e}")
    
    # Fallback: Check order level for invoice
    if not invoice_number and hasattr(order, 'invoice') and order.invoice:
        if hasattr(order.invoice, 'number'):
            invoice_number = str(order.invoice.number)
        elif hasattr(order.invoice, 'reference'):
            invoice_number = str(order.invoice.reference)
    
    print(f"Debug - Final tracking number: {tracking_number}")
    print(f"Debug - Final invoice number: {invoice_number}")
    
    # Generate tracking barcode if tracking number exists
    if tracking_number:
        try:
            tracking_barcode_img = Code128(tracking_number, writer=ImageWriter()).render()
            print(f"Debug - Successfully generated tracking barcode")
        except Exception as e:
            print(f"Debug - Error generating tracking barcode: {e}")
            tracking_barcode_img = None

    # ---------- canvas + layout (RESIZED TO 10cm × 10cm) ---------------------------
    # ─────────── geometry constants (scaled down from 13×11 to 10×10) ────────────
    PAGE_W, PAGE_H, MARGIN = 10*cm, 10*cm, 0.3*cm
    RIGHT_W                = 3.0*cm        # width of the 5-box stack (reduced from 4cm)
    STACK_PAD              = 0.15*cm       # outer edge gap (slightly reduced)
    BARCODE_SCALE          = 0.70          # barcode spans 70 % of header
    bar_h                  = 1.5*cm        # header height (reduced from 2.0cm)
    FOOTER_H               = 0.7*cm        # "Ship From" height (reduced from 0.8cm)
    QR_ROW_H               = 1.3*cm        # printed QR height (reduced from 1.8cm)
    LOGO_H                 = 1.3*cm        # printed logo height (reduced from 1.8cm)
    GAP_HEADER_TO_ADDR     = 0.3*cm        # gap after header (reduced from 0.5cm)

    # Define key vertical positions with flexible layout
    HEADER_TOP = PAGE_H - MARGIN
    HEADER_BOTTOM = HEADER_TOP - bar_h
    ADDRESS_TOP = HEADER_BOTTOM - GAP_HEADER_TO_ADDR
    
    # Fixed minimum heights for various sections
    MIN_ORDER_INFO_HEIGHT = 1.0*cm  # Minimum height for order info section (reduced)
    MIN_BETWEEN_SECTIONS = 0.3*cm   # Minimum space between sections (reduced)
    
    # Fixed positions from bottom
    BOTTOM_FOOTER_TOP = FOOTER_H + 0.2*cm
    DIVIDER_LINE_Y = 3.2*cm         # Fixed position from bottom (adjusted)
    LOGO_QR_SECTION_HEIGHT = 2.0*cm # Height needed for logo/QR section (reduced)
    
    # Calculate the available space for the address block
    MAX_ADDR_BLOCK_HEIGHT = HEADER_BOTTOM - GAP_HEADER_TO_ADDR - (DIVIDER_LINE_Y + MIN_ORDER_INFO_HEIGHT + MIN_BETWEEN_SECTIONS)
    
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))
    c.setFillColor(colors.black)

    # ─── 1. grey header (narrow) + barcode ───────────────────────
    HEADER_W_RATIO = 0.75      # grey bar = 75 % of left column width
    HEADER_PAD_X  = 0.15 * cm  # margin between barcode and grey edge (reduced)
    header_h = bar_h
    full_col_w = PAGE_W - RIGHT_W - 2*MARGIN          # width of left column
    header_w   = full_col_w * HEADER_W_RATIO          # shrink to 75 %
    header_x   = MARGIN                               # stick to left margin
    header_y   = PAGE_H - MARGIN - header_h

    # draw the narrower grey bar
    c.setFillColor(colors.lightgrey)
    c.rect(header_x, header_y, header_w, header_h, fill=1)

    # barcode dimensions inside the bar
    inner_w = header_w - 2*HEADER_PAD_X
    inner_h = header_h - 0.3*cm  # reduced padding
    inner_x = header_x + HEADER_PAD_X
    inner_y = header_y + 0.15*cm  # reduced padding

    c.drawInlineImage(barcode_img,
                    inner_x, inner_y,
                    inner_w, inner_h,
                    preserveAspectRatio=True)
                    
    # ─── 2.  right-hand box stack (without tracking number) ────────────────────────────
    RIGHT_PAD = 0.6 * cm  # padding on the right side (reduced)
    BOX_H = 0.6 * cm  # box height (reduced from 0.8cm)

    # Shrink box width to add space on the right
    actual_box_w = RIGHT_W - RIGHT_PAD

    right_x, y = PAGE_W - RIGHT_W - STACK_PAD, PAGE_H - MARGIN
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 8)  # reduced font size from 10

    # Build the box content list with dynamic data (without tracking number)
    box_contents = [
        "SURAT",
        "0.5 kg",
        shipment_date.strftime("%d/%m"),
        "PREPAID",
        "BOX 1 of 1"
    ]
    
    # Add invoice number if available
    if invoice_number:
        box_contents.append(f"INV: {invoice_number[:15]}")  # Truncate if too long

    for txt in box_contents:
        y -= BOX_H
        c.rect(right_x, y, actual_box_w, BOX_H)
        
        # Use smaller font if text is long
        text_width = c.stringWidth(txt, "Helvetica-Bold", 8)
        if text_width > actual_box_w - 0.1*cm:
            c.setFont("Helvetica-Bold", 6)  # Use smaller font
            c.drawCentredString(right_x + actual_box_w / 2,
                                y + BOX_H / 2 - 2, txt)
            c.setFont("Helvetica-Bold", 8)  # Reset to normal font
        else:
            c.drawCentredString(right_x + actual_box_w / 2,
                                y + BOX_H / 2 - 3, txt)  # adjusted centering

    # ─── 3.  Ship-To block (with dynamic layout) ────────
    import textwrap
    MAX_CHARS = 35  # reduced from 40 for smaller width
    
    # Start at the fixed position
    text_y = ADDRESS_TOP
    c.setFont("Helvetica-Bold", 5)  # reduced font
    c.drawString(MARGIN, text_y, "Ship To:")
    text_y -= 0.3*cm
    c.setFont("Helvetica", 5)  # reduced font

    # Process address lines with smart handling for long addresses
    line_height = 0.25*cm  # reduced from 0.3cm
    
    # Remove empty lines and separate address from contact info
    addr_lines_clean = []
    contact_info = []
    
    for line in addr_lines:
        if not line.strip():
            continue
        if line.startswith("Phone:") or line.startswith("Email:"):
            contact_info.append(line)
        else:
            addr_lines_clean.append(line)
    
    # Calculate total address height needed
    total_lines = 0
    for raw in addr_lines_clean:
        wrapped_lines = textwrap.wrap(raw, MAX_CHARS)
        total_lines += len(wrapped_lines)
    total_lines += len(contact_info)
    
    # Calculate total height needed for the address
    total_address_height = total_lines * line_height
    
    # Calculate the minimum height needed for order info + logo/QR section
    min_height_needed_below = MIN_ORDER_INFO_HEIGHT + MIN_BETWEEN_SECTIONS + (DIVIDER_LINE_Y - BOTTOM_FOOTER_TOP)
    
    # Calculate what's left for the address
    available_height = PAGE_H - MARGIN - bar_h - GAP_HEADER_TO_ADDR - min_height_needed_below - BOTTOM_FOOTER_TOP
    
    # Adjust font size if necessary to fit the address
    original_font_size = 7  # reduced from 8
    font_size = original_font_size
    
    if total_address_height > available_height and total_lines > 0:
        reduced_line_height = min(line_height, available_height / total_lines)
        scale_factor = reduced_line_height / line_height
        font_size = max(4, original_font_size * scale_factor)
        line_height = reduced_line_height
    
    c.setFont("Helvetica", font_size)
    
    # Render all address lines with possibly adjusted font size
    for raw in addr_lines_clean:
        wrapped_lines = textwrap.wrap(raw, MAX_CHARS)
        for line in wrapped_lines:
            c.drawString(MARGIN, text_y, line)
            text_y -= line_height
    
    # Always show contact information
    for contact_line in contact_info:
        c.drawString(MARGIN, text_y, contact_line)
        text_y -= line_height
    
    # Calculate position for order info based on where the address ended
    order_info_y = text_y - MIN_BETWEEN_SECTIONS
    
    # Ensure order info doesn't go too low
    min_order_info_y = DIVIDER_LINE_Y + MIN_ORDER_INFO_HEIGHT
    if order_info_y < min_order_info_y:
        order_info_y = min_order_info_y
    
    # ─── 4.  Order ID + date (positioned closer to divider line) ───────────
    ORDER_INFO_DIVIDER_GAP = 0.5*cm  # Space between order info bottom and divider line (reduced)
    
    # Position order info directly above the divider line
    order_info_y = DIVIDER_LINE_Y + ORDER_INFO_DIVIDER_GAP + MIN_ORDER_INFO_HEIGHT
    
    # Check if there's enough space between the end of address and the new order info position
    if text_y - MIN_BETWEEN_SECTIONS > order_info_y:
        pass
    else:
        order_info_y = text_y - MIN_BETWEEN_SECTIONS
    
    c.setFont("Helvetica-Bold", 8)  # reduced from 10
    c.drawString(MARGIN, order_info_y, f"Order ID: {order.reference}")
    order_info_y -= 0.35*cm  # reduced spacing
    c.drawString(MARGIN, order_info_y, f"Ship Date: {shipment_date:%d/%m/%Y}")

 # ─── 4.5 Tracking Number Barcode (positioned in empty space on right side) ───────────
    # ─── 4.5 Tracking Number Barcode (positioned in empty space on right side) ───────────
    if tracking_barcode_img:
        try:
            # Calculate position for tracking barcode on the right side, below invoice box
            # Use maximum available space for better scanning
            TRACKING_BARCODE_HEIGHT = 2.5*cm  # Significantly larger height for easier scanning
            TRACKING_BARCODE_WIDTH = 6.6*cm  # Keep full width
            RIGHT_MARGIN_SPACE = 3.4*cm  # Space from right edge
            
            # Find the bottom of the last box (or invoice box if it exists)
            last_box_bottom_y = y  # y is the position after drawing all boxes
            
            # Position tracking barcode below the boxes with minimal padding to maximize size
            tracking_barcode_y = last_box_bottom_y - 0.65*cm - TRACKING_BARCODE_HEIGHT
            tracking_barcode_x = PAGE_W - RIGHT_W - STACK_PAD - RIGHT_MARGIN_SPACE  # Shift left by margin amount
            
            # Draw the tracking barcode vertically in the right column with maximum size
            c.drawInlineImage(tracking_barcode_img,
                            tracking_barcode_x, 
                            tracking_barcode_y,
                            TRACKING_BARCODE_WIDTH, 
                            TRACKING_BARCODE_HEIGHT,
                            preserveAspectRatio=False)
            print(f"Debug - Tracking barcode drawn at x={tracking_barcode_x}, y={tracking_barcode_y}, width={TRACKING_BARCODE_WIDTH}, height={TRACKING_BARCODE_HEIGHT}")
        except Exception as e:
            print(f"Debug - Error drawing tracking barcode: {e}")
    # ─── 5. Horizontal divider line (fixed position) ───────────
    c.line(MARGIN, DIVIDER_LINE_Y, PAGE_W - MARGIN, DIVIDER_LINE_Y)
    
    # ─── 6.  Logo + three QRs (adjusted for smaller label) ──────────────────────
    row_y = DIVIDER_LINE_Y - 0.4*cm - QR_ROW_H  # reduced gap
    logo_w = LOGO_H * 1.8  # keep aspect ratio
    qr_sz  = QR_ROW_H
    
    c.drawInlineImage(logo_path, MARGIN, row_y, logo_w, LOGO_H, preserveAspectRatio=True)
    
    # Draw website URL centered below the logo
    url_font_size = 6  # reduced from 8
    url_y = row_y - 0.2*cm  # reduced spacing
    url_x_center = MARGIN + logo_w / 2
    c.setFont("Helvetica", url_font_size)

    text = "vicharak.in"
    text_width = c.stringWidth(text, "Helvetica", url_font_size)

    c.drawCentredString(url_x_center, url_y, text)

    c.linkURL(
        "https://vicharak.in/",
        (url_x_center - text_width/2, url_y, url_x_center + text_width/2, url_y + url_font_size),
        relative=1
    )
 
    qr_x = MARGIN + logo_w + 2.0*cm  # reduced spacing
    c.setFont("Helvetica", 6)  # reduced from 8
    for img, caption in qr_tiles:
        c.drawInlineImage(img, qr_x, row_y, qr_sz, qr_sz, preserveAspectRatio=True)
        c.drawCentredString(qr_x + qr_sz/2, row_y - 0.2*cm, caption)  # reduced spacing
        qr_x += qr_sz + 0.4*cm  # reduced spacing

    # ─── 7.  Ship-From footer (adjusted for smaller label) ─────────────────────────
    bot_y = FOOTER_H - 0.2*cm  # reduced spacing
    c.line(MARGIN, bot_y + FOOTER_H, PAGE_W - MARGIN, bot_y + FOOTER_H)

    footer_y = FOOTER_H + 0.08*cm  # reduced spacing
    c.setFont("Helvetica-Bold", 6)  # reduced from 8
    c.drawString(MARGIN, footer_y, "Ship From: VICHARAK COMPUTER PRIVATE LIMITED")

    # Add additional lines below the Ship From line
    c.setFont("Helvetica", 5)  # reduced from 7
    c.drawString(MARGIN, footer_y - 8, "Found this parcel but it's not yours?")
    c.drawString(MARGIN, footer_y - 16, "Drop us a line at contact@vicharak.in and enjoy a special discount!")

    c.save()

    # ---------- persist file --------------------------------
    rel = f"shipping_labels/SO_{order.pk}.pdf"
    abs_p = Path(settings.MEDIA_ROOT) / rel
    abs_p.parent.mkdir(parents=True, exist_ok=True)
    abs_p.unlink(missing_ok=True)
    abs_p.write_bytes(buf.getvalue())
    return rel

from django.core.mail import send_mail
from django.core.mail import EmailMultiAlternatives
import random
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.http import JsonResponse
import json
import requests
from .zoho import get_zoho_access_token, get_zoho_customers, get_zoho_customer_by_email, get_zoho_customer_by_name, get_zoho_customer_by_phone, create_zoho_customer, update_zoho_customer, get_zoho_items, create_zoho_item, normalize_phone_e164,get_zoho_invoice_details, get_zoho_invoice_pdf,get_customer_invoices,search_invoices_by_number, create_zoho_invoice, update_zoho_invoice, download_zoho_invoice_pdf, get_zoho_invoice_by_number
 
@csrf_exempt
def send_shipment_email(request):
    """
    Service function to send shipment email with Gmail-compatible formatting and invoice attachment.
    This extracts the core email logic from the API view.
    Returns: (success: bool, message: str) tuple for use in automation.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST requests are allowed'}, status=405)

    try:
        data = json.loads(request.body)
        print("[EMAIL DEBUG] Received payload:")
        print(json.dumps(data, indent=2))

        name = data.get('name')
        email = data.get('email')
        tracking_number = data.get('tracking_number')
        order_id = data.get('order_id')
        courier_company_detail = data.get('courier_company_detail', {})
        print(f"courier_company_detail{courier_company_detail}")
        invoice_id = data.get('invoice_id')  # Zoho invoice ID
        print(f"hello{invoice_id}")
        attach_invoice = data.get('attach_invoice', True)  # Option to attach invoice
        invoice_number=data.get('invoice_number')
        print(f"attach{invoice_number}")
        
        tracking_link = courier_company_detail.get('tracking_link', '#')
        # tracking_link = f"https://track.aftership.com/dtdc/{tracking_number}" if tracking_number else "#"

        part_details = data.get('part_details', [])

        if not name or not email or not tracking_number or not order_id:
            return JsonResponse({'success': False, 'message': 'Missing required fields'}, status=400)

        # Fetch the SalesOrderShipment object using the order_id and tracking_number
        shipment = SalesOrderShipment.objects.filter(order__id=order_id, tracking_number=tracking_number).first()

        if not shipment:
            return JsonResponse({'success': False, 'message': 'Shipment not found'}, status=404)

        # Check if the email has already been sent for this shipment
        if shipment.send_shipment:
            return JsonResponse({'success': False, 'message': 'Shipment email has already been sent'}, status=400)
 
        # WooCommerce API Configuration
        store = settings.WORDPRESS_STORE

        wc_store_url = store['url']
        consumer_key = store['consumer_key']
        consumer_secret = store['consumer_secret']

        # Process part details and fetch WooCommerce product info for purchased items
        line_items = []
        purchased_product_slugs = set()  # To track purchased products for exclusion in recommendations

        for part in part_details:
            try:
                part_info = part.get('part_detail', {})
                sku = part_info.get('name')  # SKU (e.g., V001936)
                quantity = part.get('quantity', 1)
                sale_price = float(part.get('sale_price', 0))
                description = part_info.get('description', '')
                internal_image = part_info.get('image', '')

                if not sku:
                    print(f"[WARNING] SKU not found for part: {part}")
                    continue

                # Fetch product details from WooCommerce using SKU
                api_url = f"{wc_store_url}/index.php?rest_route=/wc/v3/products&sku={sku}&consumer_key={consumer_key}&consumer_secret={consumer_secret}"
                response = requests.get(api_url, timeout=10)

                if response.status_code == 200:
                    products = response.json()
                    if products and len(products) > 0:
                        product = products[0]  # Get first matching product
                        wc_product_name = product.get('name', sku)
                        wc_slug = product.get('slug', sku)
                        purchased_product_slugs.add(wc_slug)  # Track purchased product

                        wc_image_url = ""
                        images = product.get('images', [])
                        if images and len(images) > 0:
                            wc_image_url = images[0].get('src', '')

                        line_item = {
                            'name': wc_product_name,
                            'quantity': int(quantity),
                            'total': sale_price * quantity,
                            'price': sale_price,
                            'sku': sku,
                            'description': description,
                            'image': {
                                'src': wc_image_url if wc_image_url else f"{wc_store_url}{internal_image}"
                            },
                            'slug': wc_slug
                        }

                        line_items.append(line_item)
                        print(f"[DEBUG] Added product: {wc_product_name} (Price: Rs.{sale_price})")
                    else:
                        print(f"[WARNING] No WooCommerce product found for SKU: {sku} - Skipping")
                else:
                    print(f"[WARNING] WooCommerce API error for SKU {sku}: {response.status_code} - Skipping")
            except Exception as e:
                print(f"[ERROR] Error processing part {part}: {str(e)}")
                continue

        if not line_items:
            return JsonResponse({'success': False, 'message': 'No valid products found in part details'}, status=400)

        # **NEW: Use Invoice Number from SalesOrderShipment**
        invoice_pdf_content = None
        invoice_filename = None
        invoice_details = None
        
        # In your views.py, replace the invoice lookup section:
        if attach_invoice and hasattr(shipment, 'invoice_number') and shipment.invoice_number:
            try:
                # Clean the invoice number - remove # and extra spaces
                invoice_number = shipment.invoice_number.strip().lstrip('#').strip()
                print(f"[INVOICE DEBUG] Found invoice number in shipment: {shipment.invoice_number}")
                print(f"[INVOICE DEBUG] Cleaned invoice number: {invoice_number}")
                
                # Search for invoice by invoice number
                matching_invoices = search_invoices_by_number(invoice_number)
                
                if matching_invoices and len(matching_invoices) > 0:
                    # Get the first matching invoice
                    invoice_basic = matching_invoices[0]
                    invoice_id = invoice_basic.get('invoice_id')
                    
                    print(f"[INVOICE DEBUG] Found matching invoice ID: {invoice_id}")
                    
                    # Get detailed invoice information
                    invoice_details = get_zoho_invoice_details(invoice_id)
                    
                    if invoice_details:
                        print(f"[INVOICE DEBUG] Invoice details retrieved successfully")
                        
                        # Download invoice PDF
                        invoice_pdf_content = get_zoho_invoice_pdf(invoice_id)
                        if invoice_pdf_content:
                            invoice_filename = f"Invoice_{invoice_number}.pdf"
                            print(f"[INVOICE DEBUG] PDF downloaded successfully: {invoice_filename}")
                        else:
                            print("[INVOICE WARNING] Failed to download PDF")
                    else:
                        print(f"[INVOICE WARNING] Could not get invoice details for ID: {invoice_id}")
                else:
                    print(f"[INVOICE WARNING] No invoice found with number: {invoice_number}")
                    
            except Exception as e:
                print(f"[INVOICE ERROR] Error fetching invoice by number: {str(e)}")


        # Fetch recommended products from WooCommerce (excluding purchased products)
        recommended_items = []
        try:
            # Fetch all products (up to 3 for recommendations)
            rec_api_url = f"{wc_store_url}/index.php?rest_route=/wc/v3/products&consumer_key={consumer_key}&consumer_secret={consumer_secret}&per_page=10"
            rec_response = requests.get(rec_api_url, timeout=10)
            
            # print response status code for debugging
            print(f"[DEBUG] Recommended products API response status: {rec_response.status_code}")

            if rec_response.status_code == 200:
                all_products = rec_response.json()
                # Filter out purchased products
                available_products = [
                    product for product in all_products
                    if product.get('slug') not in purchased_product_slugs
                ]
                
                # print available products 
                print(f"[DEBUG] Available products for recommendations: {len(available_products)} found")

                # Randomly select up to 3 products for recommendations
                if len(available_products) > 3:
                    available_products = random.sample(available_products, 3)

                for product in available_products:
                    print("[DEBUG] Processing recommended product")

                    rec_image_url = ""
                    images = product.get('images', [])
                    if images and len(images) > 0:
                        rec_image_url = images[0].get('src', '')

                    recommended_item = {
                        'name': product.get('name', ''),
                        'slug': product.get('slug', ''),
                        'permalink': product.get('permalink', ''),
                        'price': float(product.get('price', 0)),
                        'image': {
                            'src': rec_image_url
                        }
                    }
                    recommended_items.append(recommended_item)
                    print(f"[DEBUG] Added recommended product: {recommended_item['name']} (Price: Rs.{recommended_item['price']})")
            else:
                print(f"[WARNING] WooCommerce API error for recommended products: {rec_response.status_code}")
        except Exception as e:
            print(f"[ERROR] Error fetching recommended products: {str(e)}")

        # Prepare email subject with invoice info if available
        subject_suffix = ""
        if invoice_details:
            invoice_number = invoice_details.get('invoice_number', '')
            if invoice_number:
                subject_suffix = f" - Invoice #{invoice_number}"
        
        subject = f'Your order is confirmed! - Order #{order_id}{subject_suffix}'
        from_email = "Vicharak Sales Team <sales@vicharak.in>"
        to = [email]

        # Generate HTML for purchased products
        product_html = ""
        product_names = []
        total_amount = 0

        for item in line_items:
            image_url = item['image']['src'] if item.get('image') and item['image'].get('src') else ''
            product_name = item['slug'].replace('-', ' ').upper()
            product_names.append(product_name)
            total_amount += float(item['total'])

            product_html += f"""
            <tr>
                <td style="width: 80px; padding: 15px 15px 15px 0; ">
                    <img src="{image_url}" alt="{item['name']}" style="width: 80px; height: 60px; object-fit: cover; border-radius: 6px; display: block;">
                </td>
                <td style="padding: 15px 10px;">
                    <div style="font-size: 14px; font-weight: 600; color: #333333; margin-bottom: 5px;">{product_name}</div>
                </td>
                <td style="width: 80px; padding: 15px 10px; text-align: center; font-size: 14px; font-weight: 500; color: #333333;">
                    {item['quantity']} pc{'s' if item['quantity'] != 1 else ''}
                </td>
                <td style="width: 100px; padding: 15px 0 15px 10px; text-align: right; font-size: 14px; font-weight: 600; color: #333333;">
                    Rs. {float(item['total']):,.2f}
                </td>
            </tr>
            """

        product_names_str = ", ".join(product_names)

        # Add total row if invoice details are available
        if invoice_details:
            invoice_total = invoice_details.get('total', total_amount)
            product_html += f"""
            <tr style="border-top: 2px solid #333333;">
                <td colspan="3" style="padding: 15px 10px; text-align: right; font-size: 16px; font-weight: 700; color: #333333;">
                    Total Amount:
                </td>
                <td style="width: 100px; padding: 15px 0 15px 10px; text-align: right; font-size: 16px; font-weight: 700; color: #333333;">
                    Rs. {float(invoice_total):,.2f}
                </td>
            </tr>
            """

        # Generate HTML for recommended products - Mobile responsive
        recommended_html = ""
        for item in recommended_items:
            image_url = item['image']['src'] if item.get('image') and item['image'].get('src') else ''
            permalink = item.get('permalink', '#')

            recommended_html += f"""
            <a href="{permalink}" target="_blank" style="text-decoration: none;">
                <div class="recommended-item" style="width: 100%; max-width: 140px; display: inline-block; vertical-align: top; margin: 10px; text-align: center;">
                    <div>
                        <img src="{image_url}" alt="{item['name']}" style="width: 100%; height: 120px; object-fit: cover; display: block; border-radius: 6px;">
                    </div>
                    <div style="background-color: #ffffff; padding: 8px; text-align: left; border-radius: 6px;">
                        <div style="font-size: 12px; font-weight: 500; color: #333333; margin-bottom: 5px; line-height: 1.3;">
                            {item.get('slug', '').replace('-', ' ').title()}
                        </div>
                        <div style="font-size: 12px; font-weight: 600; color: #333333;">
                            ₹{float(item['price']):,.2f}
                        </div>
                    </div>
                </div>
            </a>
            """

        # Add invoice info section if available
        invoice_section = ""
        if invoice_details:
            invoice_number = invoice_details.get('invoice_number', '')
            invoice_date = invoice_details.get('date', '')
            invoice_section = f"""
            <!-- Invoice Info Section -->
            <div style="background-color: #E8F5E8; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #4CAF50;">
                <div style="font-size: 16px; font-weight: 600; color: #2E7D32; margin-bottom: 10px;">📄 Invoice Attached</div>
                <div style="font-size: 14px; color: #333333; margin-bottom: 5px;">Invoice Number: <strong>{invoice_number}</strong></div>
                <div style="font-size: 14px; color: #333333;">Invoice Date: <strong>{invoice_date}</strong></div>
                <div style="font-size: 12px; color: #666666; margin-top: 10px;">Please find your invoice attached to this email for your records.</div>
            </div>
            """

        # Gmail-compatible HTML email template with responsive design
        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Your order is confirmed! - Vicharak</title>
            <style>
                @media only screen and (max-width: 600px) {{
                    .container {{
                        width: 100% !important;
                        max-width: 100% !important;
                        margin: 0 !important;
                    }}
                    .content-padding {{
                        padding: 20px 15px !important;
                    }}
                    .header-padding {{
                        padding: 30px 15px !important;
                    }}
                    .footer-padding {{
                        padding: 20px 15px !important;
                    }}
                    .track-section {{
                        display: block !important;
                        text-align: center !important;
                    }}
                    .track-button {{
                        display: block !important;
                        margin-bottom: 15px !important;
                        /* text-align: center !important;*/
                    }}
                    .awb-number {{
                        text-align: center !important;
                    }}
                    .resources-row {{
                        display: block !important;
                    }}
                    .resource-item {{
                        display: block !important;
                        width: 100% !important;
                        padding: 15px 0 !important;
                        text-align: start !important;
                        border-bottom: 1px solid #e0e0e0;
                    }}
                    .resource-item:last-child {{
                        border-bottom: none !important;
                    }}
                    .recommended-container {{
                        text-align: center !important;
                    }}
                    .recommended-item {{
                        display: block !important;
                        width: 100% !important;
                        max-width: 280px !important;
                        margin: 15px auto !important;
                    }}
                    .logo-container {{
                        text-align: center !important;
                        padding-top: 20px !important;
                    }}
                    .logo-container img {{
                        max-width: 80px !important;
                    }}
                    .header-title {{
                        text-align: center !important;
                        font-size: 24px !important;
                    }}
                }}
            </style>
        </head>
        <body style="margin: 0; padding: 0; font-family: Arial, sans-serif; background-color: #f5f5f5;">
            <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background-color: #f5f5f5;">
                <tr>
                    <td style="padding: 20px 10px;">
                        <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" class="container" style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 12px;">
                            
                            <!-- Header -->
                            <tr>
                                <td style="background: linear-gradient(135deg, #000000, #333333); color: #ffffff; padding: 40px 30px; border-radius: 12px 12px 0 0;" class="header-padding">
                                    <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%">
                                        <tr>
                                            <td style="vertical-align: middle;">
                                                <h1 class="header-title" style="margin: 0; font-size: 28px; font-weight: 700; color: #ffffff;">Your {product_names_str} is on the way.</h1>
                                            </td>
                                            <td class="logo-container" style="width: 120px; text-align: right; vertical-align: middle;">
                                                <img src="https://store.vicharak.in/wp-content/uploads/2024/11/VICHARAK-WHITE-LOGO-HD-PNG-2@2x.png" alt="Vicharak Logo" style="max-width: 100px; height: auto; border-radius: 8px;">
                                            </td>
                                        </tr>
                                    </table>
                                </td>
                            </tr>
                            
                            <!-- Content -->
                            <tr>
                                <td class="content-padding" style="padding: 30px;">
                                    <div style="font-size: 24px; font-weight: 600; color: #333333; margin-bottom: 15px;">Hello {name},</div>
                                    <div style="font-size: 16px; color: #666666; margin-bottom: 30px; line-height: 1.5;">We're happy to inform you that your unit is now ready for pickup.</div>
                                    
                                    <!-- Track Button Section -->
                                    <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" class="track-section" style="margin-bottom: 40px;">
                                        <tr>
                                            <td class="track-button" style="">
                                                 <div style="margin-bottom: 10px; font-size: 16px; font-weight: 600; color: #333333; text-align: start; ">AWB: {tracking_number}</div>
                                                <a href="{tracking_link}" style="display: inline-block; background-color: #000000; color: #ffffff; padding: 15px 30px; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 16px;" target="_blank">Track your Package</a>
                                            </td>
                                        </tr>
                                    </table>
                                    
                                    {invoice_section}
                                    
                                    <!-- Divider -->
                                    <div style="height: 1px; background-color: #e0e0e0; margin: 30px 0;"></div>
                                    
                                    <!-- Order Section -->
                                    <div style="background-color: #F3F3F3; padding: 25px; border-radius: 8px; margin: 30px 0;">
                                        <div style="text-align: center; font-size: 18px; font-weight: 600; color: #333333; margin-bottom: 25px;">Order no. - #{order_id}</div>
                                        
                                        <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%">
                                            {product_html}
                                        </table>
                                    </div>
                                    
                                    <!-- Divider -->
                                    <div style="height: 1px; background-color: #e0e0e0; margin: 30px 0;"></div>
                                    
                                    <!-- Resources Section -->
                                    <div style="background-color: #F3F3F3; padding: 25px; border-radius: 8px; margin: 30px 0;">
                                        <div style="font-size: 20px; font-weight: 600; color: #333333; margin-bottom: 20px;">Must Read</div>
                                        <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" class="resources-row">
                                            <tr>
                                                <td class="resource-item" style="padding: 10px 0; font-size: 12px;">
                                                    <a href="https://docs.vicharak.in/" target="_blank" style="color: #333333; text-decoration: none; display: block;">
                                                        <span style="font-size: 14px; margin-right: 8px;">📄</span>
                                                        <span style="border-bottom: 1px solid #333333;">Documentation & Setup Guide</span>
                                                    </a>
                                                </td>
                                                <td class="resource-item" style="padding: 10px 0; font-size: 12px;">
                                                    <a href="https://docs.vicharak.in/vicharak_sbcs/axon/axon-getting-started/" target="_blank" style="color: #333333; text-decoration: none; display: block;">
                                                        <span style="font-size: 14px; margin-right: 8px;">🔌</span>
                                                        <span style="border-bottom: 1px solid #333333;">Adapter Specification</span>
                                                    </a>
                                                </td>
                                                <td class="resource-item" style="padding: 10px 0; font-size: 12px;">
                                                    <a href="https://discord.gg/V89ZR2vbhu" target="_blank" style="color: #333333; text-decoration: none; display: block;">
                                                        <span style="font-size: 14px; margin-right: 8px;">💻</span>
                                                        <span style="border-bottom: 1px solid #333333;">Community Server</span>
                                                    </a>
                                                </td>
                                            </tr>
                                        </table>
                                    </div>
                                    
                                    <!-- Recommended Products Section -->
                                    <div style="padding: 25px; border-radius: 8px; margin: 30px 0; background: linear-gradient(108.45deg, #EFF6FF 5.68%, #F0F6FF 18.34%, #F9F5FF 94.04%);">
                                        <div style="font-size: 20px; font-weight: 600; margin-bottom: 10px; color: #2B60EB;">Complete Your Setup</div>
                                        <div style="font-size: 14px; color: #000000; font-weight: 500; margin-bottom: 20px;">Don't miss out on these popular accessories that work perfectly with your order!</div>
                                        
                                        <div class="recommended-container" style="text-align: center;">
                                            {recommended_html}
                                        </div>
                                        
                                        <div style="text-align: center; margin-top: 20px;">
                                            <div style="display: inline-block; text-align: center; font-size: 14px; color: #000000; font-weight: 500; border: 1px solid #2B60EB; border-radius: 25px; padding: 10px 15px;">
                                                ✨ Free shipping on order over ₹500
                                            </div>
                                        </div>
                                    </div>
                                    
                                    <!-- Note Section -->
                                    <div style="margin: 30px 0;">
                                        <div style="font-size: 14px; color: #666666; margin-bottom: 20px; line-height: 1.5;">
                                            <strong>Note:</strong> Please note that the tracking will be active within the next 12 to 15 hours.
                                        </div>
                                        
                                        <div style="font-size: 16px; color: #333333; font-weight: 500; line-height: 1.5;">
                                            <strong>Thank you for choosing Vicharak.</strong> If you have any questions or need further assistance, feel free to reach out.
                                        </div>
                                    </div>
                                </td>
                            </tr>
                            
                            <!-- Footer -->
                            <tr>
                                <td class="footer-padding" style="background-color: #000000; color: #ffffff; padding: 30px; text-align: center; border-radius: 0 0 12px 12px;">
                                    <div style="font-size: 16px; margin-bottom: 10px;">Best regards,</div>
                                    <div style="font-size: 18px; font-weight: 600; margin-bottom: 20px;">Sales Team</div>
                                    <div style="font-size: 12px; color: #cccccc;">2025 © Vicharak. All rights reserved.</div>
                                </td>
                            </tr>
                            
                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """

        # Create the email message
        email_msg = EmailMultiAlternatives(
            subject,
            'This is an HTML email. Please view it in an HTML-compatible email client.',  # Fallback text
            from_email,
            to
        )
        email_msg.attach_alternative(html_content, "text/html")
        
        # Attach invoice PDF if available
        if invoice_pdf_content and invoice_filename:
            try:
                email_msg.attach(invoice_filename, invoice_pdf_content, 'application/pdf')
                print(f"[INVOICE DEBUG] Invoice PDF attached: {invoice_filename}")
            except Exception as e:
                print(f"[INVOICE ERROR] Failed to attach PDF: {str(e)}")

        # Send the email
        email_msg.send()
        print("[EMAIL DEBUG] Email sent successfully")

        # Update shipment status after sending the email
        shipment.send_shipment = True
        shipment.save()

        success_message = 'Email sent successfully'
        if invoice_filename:
            success_message += f' with invoice attachment ({invoice_filename})'

        return JsonResponse({'success': True, 'message': success_message})

    except Exception as e:
        print(f"[EMAIL ERROR] {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

import json
import logging
import traceback
import requests
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import re
from order.models import SalesOrder, SalesOrderShipment

logger = logging.getLogger(__name__)

# def create_zoho_invoice_fun(order_id):
#     try:
#         if not order_id:
#             return JsonResponse({'error': 'Missing order_id in request'}, status=400)

#         order = SalesOrder.objects.get(id=order_id)
        
#         # print key and value of order
#         # print("[DEBUG] SalesOrder Fields:")
#         # for field in order._meta.fields:
#         #     val = getattr(order, field.name)
#         #     print(f"  {field.name}: {val}")
        
#         customer = order.customer
#         # print key and value of customer
#         # print("[DEBUG] Customer Fields:")
#         # for field in dir(customer):
#         #     if not field.startswith("_"):
#         #         try:
#         #             value = getattr(customer, field)
#         #             if not callable(value):
#         #                 print(f"  {field}: {value}")
#         #         except:
#         #             pass

#         # ------------------- Customer Check -------------------
#         zoho_customers = get_zoho_customers()
#         zoho_customer = None

#         # Try to match by email first
#         if customer.email:
#             zoho_customer = next((c for c in zoho_customers if c.get("email", "").lower() == customer.email.lower()), None)

#         # If email not matched, match by normalized international phone
#         if not zoho_customer and customer.phone:
#             normalized_customer_phone = normalize_phone_e164(customer.phone)

#             for c in zoho_customers:
#                 zoho_phone = normalize_phone_e164(c.get("phone", ""))
#                 zoho_mobile = normalize_phone_e164(c.get("mobile", ""))

#                 print(f"[DEBUG] Comparing with Zoho phone: {zoho_phone} and mobile: {zoho_mobile}")

#                 if normalized_customer_phone:
#                     if normalized_customer_phone == zoho_phone or normalized_customer_phone == zoho_mobile:
#                         zoho_customer = c
#                         print(f"[DEBUG] Match found with contact: {zoho_customer.get('contact_name')}")
#                         break

#         # Create new Zoho customer if not found
#         if not zoho_customer:
#             print("[DEBUG] Customer not found in Zoho. Creating new customer.")
#             result = create_zoho_customer(customer)
#             contact_id = result.get("contact_id")
#             message = result.get("message", "Customer created.")
#         else:
#             contact_id = zoho_customer["contact_id"]
#             message = "Customer already exists in Zoho."

#         print("[DEBUG] Customer ID:", contact_id)
#         print("[DEBUG] Message:", message)

#         # Prepare the JSON response
#         if contact_id and contact_id.startswith("2508"):  # Adjust prefix if needed
#             return JsonResponse({"success": True, "message": message})
#         else:
#             return JsonResponse({"success": False, "message": message})
        
#     except Exception as e:
#         tb = traceback.format_exc()
#         logger.error(f"[ERROR] Exception: {str(e)}\nTraceback:\n{tb}")
#         return JsonResponse({'error': str(e), 'traceback': tb}, status=400)
    
store = settings.WORDPRESS_STORE
wc_store_url = store['url']
consumer_key = store['consumer_key']
consumer_secret = store['consumer_secret']

def get_wordpress_shipping_charge(order_id):
    api_url = f"{wc_store_url}/index.php?rest_route=/wc/v3/orders/{order_id}&consumer_key={consumer_key}&consumer_secret={consumer_secret}"
    try:
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()
        data = response.json()

        # WooCommerce shipping_lines is a list of shipping charges
        shipping_lines = data.get("shipping_lines", [])
        total_shipping = sum(float(line.get("total", 0)) for line in shipping_lines)
        return total_shipping
    except Exception as e:
        print(f"[ERROR] Could not fetch shipping for WordPress order {order_id}: {e}")
        return 0.0


def find_or_create_zoho_customer(customer):
    """
    Returns a tuple: (contact_id, message, source)
    source: 'email', 'phone', 'name', 'created'
    """
    contact_id = None
    source = None

    # 1️⃣ Check by email
    if customer.email:
        print(f"[DEBUG] Searching Zoho customer by email: {customer.email}")
        zoho_customer = get_zoho_customer_by_email(customer.email)
        if zoho_customer:
            contact_id = zoho_customer.get("contact_id")
            source = "email"
            update_resp = update_zoho_customer(contact_id, customer)
            return contact_id, "Customer updated in Zoho", source

    # 2️⃣ Check by phone
    if customer.phone:
        print(f"[DEBUG] Searching Zoho customer by phone: {customer.phone}")
        zoho_customer = get_zoho_customer_by_phone(customer.phone)
        if zoho_customer:
            contact_id = zoho_customer.get("contact_id")
            source = "phone"
            update_resp = update_zoho_customer(contact_id, customer)
            return contact_id, "Customer updated in Zoho", source

    # 3️⃣ Check by name
    search_name = customer.name or customer.individual_name or customer.contact
    if search_name:
        print(f"[DEBUG] Searching Zoho customer by name: {search_name}")
        zoho_customer = get_zoho_customer_by_name(search_name)
        if zoho_customer:
            contact_id = zoho_customer.get("contact_id")
            source = "name"
            update_resp = update_zoho_customer(contact_id, customer)
            return contact_id, "Customer updated in Zoho", source

    # 4️⃣ Create new customer if not found
    result = create_zoho_customer(customer)
    contact_id = result.get("contact_id")
    source = "created"
    message = result.get("message", "Customer created in Zoho.")
    return contact_id, message, source

def create_zoho_invoice_fun(order_id):
    try:
        if not order_id:
            return JsonResponse({'error': 'Missing order_id in request'}, status=400)

        order = SalesOrder.objects.get(id=order_id)
        print(f"[DEBUG] Processing SalesOrder ID: {order.id}, Number of line items: {order.lines.count()}")

        # ✅ Skip if order doesn't have WordPress order ID
        # if not getattr(order, "wordpress_order_id", None):
        #     print(f"[INFO] Skipping Zoho invoice creation — no WordPress order ID for SalesOrder {order.id}")
        #     return JsonResponse({
        #         "success": False,
        #         "message": f"Skipped Zoho invoice creation — WordPress order ID not found for SalesOrder {order.id}"
        #     })
        # ------------------- Customer Check -------------------
        customer = order.customer
        contact_id, message, source = find_or_create_zoho_customer(customer)
        print(f"[DEBUG] Using Zoho contact_id: {contact_id} (found via: {source}) for SalesOrder ID: {order.id}")

        # ------------------- Line Items -------------------
        zoho_items = get_zoho_items()
        invoice_line_items = []

        for line in order.lines.all():
            part = line.part
            part_name = part.full_name
            part_name_lower = part_name.lower()
            print(f"[DEBUG] Processing line item: {part_name}, Qty: {line.quantity}, Unit Price: {line.sale_price}")

            # Try match by SKU
            zoho_item = next((i for i in zoho_items if part_name_lower == (i.get("sku") or "").lower()), None)

            if not zoho_item:
                fallback_name = (part.category.name if part.category else part.full_name).lower()
                zoho_item = next((i for i in zoho_items if (i.get("name") or "").lower() == fallback_name), None)

            if not zoho_item:
                item_id = create_zoho_item(line)
                item_name = part.full_name
                print(f"[DEBUG] Zoho item not found. Created new item: {item_name} (ID: {item_id})")
            else:
                item_id = zoho_item.get("item_id")
                item_name = zoho_item.get("name")
                print(f"[DEBUG] Found existing Zoho item: {item_name} (ID: {item_id})")

            rate = float(line.sale_price.amount) if line.sale_price else 0.0
            invoice_line_items.append({
                "item_id": item_id,
                "name": item_name,
                "quantity": float(line.quantity),
                "description": part.description or part.full_name,
                # "gst_treatment": "business_gst",
                # "gst_no": "24AAJCV8134E1ZB",
            })

        # ------------------- Shipping Charge -------------------
        if getattr(order, "wordpress_order_id", None):
            shipping_charge = get_wordpress_shipping_charge(order.wordpress_order_id)
            print(f"[DEBUG] Shipping charge from WordPress: {shipping_charge}")
        else:
            shipping_charge = 120.0   # ✅ Default changed from 100.0 → 120.0
            print(f"[DEBUG] Default shipping charge applied: {shipping_charge}")

        # ------------------- Check Existing Invoice -------------------
        shipment = SalesOrderShipment.objects.filter(order=order).last() 
        existing_invoice_number = getattr(shipment, "invoice_number", None)

        if existing_invoice_number:
            print(f"[DEBUG] Checking for existing Zoho Invoice by number: {existing_invoice_number}")

            # Try fetching the invoice from Zoho
            existing_invoice_data = get_zoho_invoice_by_number(existing_invoice_number)

            if existing_invoice_data and existing_invoice_data.get("invoice_id"):
                existing_invoice_id = existing_invoice_data["invoice_id"]
                print(f"[DEBUG] Existing Zoho Invoice found (ID: {existing_invoice_id}), updating instead of creating...")
                invoice_response = update_zoho_invoice(
                    existing_invoice_id, contact_id, invoice_line_items, shipping_charge
                )
            else:
                print(f"[DEBUG] No Zoho invoice found with number {existing_invoice_number}, creating new one...")
                invoice_response = {
                "success": False,
                "message": f"Invoice number '{existing_invoice_number}' exists in system but not found in Zoho — skipped creation.",
                "invoice_id": None,
               }

                # invoice_response = create_zoho_invoice(
                #     contact_id, invoice_line_items, shipping_charge=shipping_charge
                # )
        else:
            print("[DEBUG] No existing invoice number found. Creating new Zoho Invoice...")
            invoice_response = create_zoho_invoice(
                contact_id, invoice_line_items, shipping_charge=shipping_charge
            )

        print(f"[DEBUG] Zoho invoice response:", json.dumps(invoice_response, indent=2))

        # ------------------- Save Invoice Number and ID -------------------
        if invoice_response.get("success"):
            invoice_id = invoice_response.get("invoice_id")
            invoice_data = invoice_response.get("invoice", {})
            invoice_number = invoice_data.get("invoice_number") or invoice_data.get("invoice_number_display") or ""

            if shipment:
                shipment.invoice_id = invoice_id
                shipment.invoice_number = invoice_number
                shipment.save(update_fields=["invoice_id", "invoice_number"])
                print(f"[DEBUG] Saved Invoice → ID: {invoice_id}, Number: {invoice_number}")
            else:
                print("[DEBUG] No SalesOrderShipment found to update — consider creating one")

        response_data = {
            "success": invoice_response.get("success", False),
            "message": invoice_response.get("message", ""),
            "invoice_id": invoice_response.get("invoice_id"),
            "customer_id": contact_id,
            "line_items": invoice_line_items
        }

        return JsonResponse(response_data)

    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"[ERROR] Exception: {str(e)}\nTraceback:\n{tb}")
        return JsonResponse({'error': str(e), 'traceback': tb}, status=400)
    
# for test call create_zoho_invoice_fun(282)

# result = create_zoho_invoice_fun(520)
# print(result.content.decode()) 

import threading
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from order.models import SalesOrderLineItem
from utils.invoice_context import is_invoice_sync_disabled, disable_invoice_sync, enable_invoice_sync

def async_create_invoice(order_id):
    print(f"[INFO] Starting async Zoho invoice creation for order {order_id}") 
    try:
        create_zoho_invoice_fun(order_id)
    except Exception as e:
        print(f"[ERROR] Failed to sync Zoho invoice for order {order_id}: {e}")

# @receiver([post_save, post_delete], sender=SalesOrderLineItem)
def sync_zoho_invoice(sender, instance, **kwargs):
    
    # ⛔ Skip invoice if scan-and-ship is running
    if is_invoice_sync_disabled():
        print("[DEBUG] Invoice sync skipped (scan & ship in progress)")
        return
    
    order = instance.order
    threading.Thread(target=async_create_invoice, args=(order.id,)).start()

     
def create_zoho_invoices_for_pending_orders(output_file="zoho_invoice_results.json"):
    """
    Create/update Zoho invoices for all pending sales orders.
    Logs each result immediately after processing.
    """
    PENDING_STATUS = 10  # adjust according to your SalesOrder status values
    pending_orders = SalesOrder.objects.filter(status=PENDING_STATUS)

    created_count = 0
    updated_count = 0
    failed_count = 0
    processed_count = 0

    # Open file in write mode and start JSON array
    with open(output_file, "w") as f:
        f.write("[\n")

        for index, order in enumerate(pending_orders):
            try:
                print(f"[INFO] Processing SalesOrder ID: {order.id}")
                response = create_zoho_invoice_fun(order.id)

                # 🧠 Convert JsonResponse to dict safely
                if isinstance(response, JsonResponse):
                    data = json.loads(response.content.decode())
                elif isinstance(response, dict):
                    data = response
                else:
                    try:
                        data = response.json()
                    except Exception:
                        data = {"success": False, "message": "Unexpected response type"}

                if data.get("success"):
                    if "updated" in data.get("message", "").lower():
                        updated_count += 1
                        status_text = "updated"
                    else:
                        created_count += 1
                        status_text = "created"
                else:
                    failed_count += 1
                    status_text = "failed"

                record = {
                    "order_id": order.id,
                    "status": status_text,
                    "success": data.get("success", False),
                    "message": data.get("message", ""),
                    "invoice_id": data.get("invoice_id")
                }

            except Exception as e:
                failed_count += 1
                record = {
                    "order_id": order.id,
                    "status": "failed",
                    "success": False,
                    "message": str(e),
                    "invoice_id": None
                }

            # ✅ Write the record immediately to file
            json.dump(record, f, indent=2)
            processed_count += 1

            # Add comma unless it’s the last record
            if index < pending_orders.count() - 1:
                f.write(",\n")
            else:
                f.write("\n")

            print(f"[LOGGED] Order {order.id} → {record['status']}")

        # Close JSON array properly
        f.write("]\n")

    print("\n[INFO] Zoho invoice processing completed.")
    print(f"Total processed: {processed_count}")
    print(f"Created invoices: {created_count}")
    print(f"Updated invoices: {updated_count}")
    print(f"Failed: {failed_count}")
    print(f"[INFO] Results written incrementally to: {output_file}")
    
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from collections import defaultdict
from datetime import date
from django.db.models import Sum
from django.core.cache import cache

from build.models import Build
from order.models import PurchaseOrder
from part.models import Part

@login_required
def purchase_order_build_impact(request):
    from time import time

    total_start = time()
    print("⏱️ Started processing build impact")
    today = date.today()
    cache_key = "build_impact_report"
    cached = cache.get(cache_key)
    if cached:
        return JsonResponse(cached)

    active_po_statuses = [10, 20]
    active_build_statuses = [10, 20]

    # Step 1: Incoming PO Stock
    s1 = time()
    incoming_stock = defaultdict(Decimal)
    po_part_ids = set()

    po_qs = PurchaseOrder.objects.filter(status__in=active_po_statuses).prefetch_related('lines__part__part')
    for po in po_qs:
        for line in po.lines.all():
            part = line.part.part if line.part and line.part.part else None
            if part:
                incoming_stock[part.id] += Decimal(line.quantity)
                po_part_ids.add(part.id)
    print(f"✅ Incoming PO stock loaded in {time() - s1:.2f}s")

    # Step 2: Load BuildLines and related parts
    s2 = time()
    builds = Build.objects.filter(status__in=active_build_statuses).order_by("target_date", "id")
    build_lines = []
    for build in builds:
        lines = build.build_lines.all() if hasattr(build, 'build_lines') else build.lines.all()
        for line in lines:
            build_lines.append((build, line))
    print(f"✅ BuildLines with allocations loaded in {time() - s2:.2f}s")

    # Step 3: Load parts only used in builds or POs
    s3 = time()
    build_part_ids = {line.part.id for _, line in build_lines if line.part}
    all_part_ids = build_part_ids | po_part_ids

    parts_qs = Part.objects.filter(id__in=all_part_ids)
    parts_map = {}

    for part in parts_qs:
        try:
            stock = Decimal(part.available_stock)  # access @property safely
        except Exception:
            stock = Decimal(0)
        parts_map[part.id] = {
            "part": part,
            "name": part.name,
            "stock": stock
        }

    working_available = {pid: data["stock"] for pid, data in parts_map.items()}
    working_incoming = incoming_stock.copy()
    print(f"✅ Parts loaded in {time() - s3:.2f}s")

    # Step 4: Calculate impact per build
    s4 = time()
    results = []

    for build in builds:
        lines = [line for b, line in build_lines if b.id == build.id]
        can_fulfill = True
        part_data = []
        possible_counts = []

        for item in lines:
            part = item.part
            if not part:
                continue

            part_id = part.id
            required = item.quantity
            allocated = item.allocated_quantity()
            need = required - allocated

            avail = min(working_available.get(part_id, Decimal(0)), need)
            working_available[part_id] -= avail
            remaining = need - avail

            po_stock = working_incoming.get(part_id, Decimal(0))
            use_po = min(po_stock, remaining)
            working_incoming[part_id] -= use_po
            remaining -= use_po

            total_used = avail + use_po
            unit_required = required / build.quantity if build.quantity else required
            possible = total_used // unit_required if unit_required > 0 else 0
            possible_counts.append(int(possible))

            shortfall = remaining if remaining > 0 else Decimal(0)
            if shortfall > 0:
                can_fulfill = False

            part_data.append({
                "part": {
                    "id": part.id,
                    "name": part.name,
                    "IPN": part.IPN,
                    "description": part.description,
                },
                "required": required,
                "available_stock": avail,
                "available_stock_total": parts_map[part_id]["stock"],
                "incoming_stock": use_po,
                "incoming_stock_total": incoming_stock.get(part_id, Decimal(0)),
                "virtual_stock": total_used,
                "shortfall": shortfall,
                "can_fulfill": shortfall == 0,
            })

        max_possible = min(possible_counts) if possible_counts else 0
        results.append({
            "build": build.reference,
            "build_id": build.id,  # Required for form field names
            "can_fulfill": can_fulfill,
            "max_build_possible": max_possible,
            "parts": part_data,
        })


    print(f"✅ Build impact processed in {time() - s4:.2f}s")
    print(f"✅ Total time: {time() - total_start:.2f}s")

    pending_pos = PurchaseOrder.objects.filter(status__in=[10, 20]).order_by("target_date")
    print(f"✅ Pending POs loaded: {pending_pos.count()}")
    # Compute everything
    context_results = {
        "results": results,
        "pending_pos": list(pending_pos.values("id", "reference", "supplier__name", "target_date")),
    }
    # Set only results in cache (it's safe)
    cache.set(cache_key, context_results, timeout=60)

    # Combine for rendering
    context = {
        "results": results,
        "pending_pos": pending_pos,
    }
    # Instead of render
    return JsonResponse(context_results)

import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from order.models import PurchaseOrder, PurchaseOrderLineItem
from part.models import Part, SupplierPart
from company.models import ManufacturerPart


@csrf_exempt
@login_required
def assign_shortfalls_to_po(request):
    print("🔧 assign_shortfalls_to_po called")

    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Invalid method"}, status=405)

    try:
        data = json.loads(request.body)
        po_id = data.get("selected_po")
        selected_keys = data.get("selected_parts", [])

        print(f"📦 Received PO ID: {po_id}")
        print(f"🧩 Selected Keys: {selected_keys}")

        if not po_id or not selected_keys:
            print("❌ Missing PO ID or selected parts")
            return JsonResponse({"success": False, "message": "Missing PO or parts."}, status=400)

        try:
            po = PurchaseOrder.objects.get(id=po_id)
            print(f"✅ Found PO: {po}")
        except PurchaseOrder.DoesNotExist:
            return JsonResponse({"success": False, "message": "PO not found"}, status=404)

        assigned_items = []
        for key in selected_keys:
            try:
                build_id, part_id = key.split("::")
                shortfall_key = f"shortfall_{build_id}_{part_id}"
                shortfall_qty = Decimal(str(data.get(shortfall_key, 0)).strip())

                print(f"➡️ Processing key: {key} → {shortfall_qty}")

                if shortfall_qty <= 0:
                    print(f"⚠️ Skipping zero/negative shortfall: {shortfall_qty}")
                    continue

                part = Part.objects.get(id=part_id)

                supplier_part = SupplierPart.objects.filter(part=part, supplier=po.supplier).first()

                if not supplier_part:
                    manufacturer_part = getattr(part, 'manufacturer_part', None)
                    if not manufacturer_part:
                        manufacturer_part = ManufacturerPart.objects.filter(part=part).first()

                    sku = part.IPN or part.name or "AUTO-GEN"

                    supplier_part = SupplierPart.objects.create(
                        part=part,
                        supplier=po.supplier,
                        SKU=sku,
                        link="",
                        note=f"Auto-created for PO #{po.reference}",
                        manufacturer_part=manufacturer_part,
                    )
                    print(f"🆕 Created SupplierPart: {supplier_part}")

                line_item, created = PurchaseOrderLineItem.objects.get_or_create(
                    order=po,
                    part=supplier_part,
                    defaults={
                        "quantity": shortfall_qty,
                        "purchase_price": Decimal("0.00"),
                        "purchase_price_currency": po.currency,
                        "reference": f"Shortfall from Build {build_id}",
                    }
                )

                if not created:
                    line_item.quantity += shortfall_qty
                    line_item.save()

                print(f"✅ Assigned {shortfall_qty} of {supplier_part} to PO #{po.reference}")

                assigned_items.append({
                    "build_id": build_id,
                    "part_id": part_id,
                    "qty": float(shortfall_qty),
                })

            except Exception as e:
                print(f"❌ Error for key {key}: {e}")
                continue

        print("✅ Assignment complete.")
        return JsonResponse({"success": True, "assigned": assigned_items})

    except Exception as e:
        print(f"❌ Fatal error: {e}")
        return JsonResponse({"success": False, "message": str(e)}, status=500)

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from django.utils import timezone
from order.models import SalesOrder, SalesOrderShipment, SalesOrderAllocation, SalesOrderScanHistory
from stock.models import StockItem
from django.db.models import Q
from django.utils.dateparse import parse_date

def record_scan(barcode, order, shipment, user, status, message, log):
    SalesOrderScanHistory.objects.create(
        barcode=barcode,
        order=order,
        shipment=shipment,
        user=user,
        status=status,
        message=message,
        log=log,
    )

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def scan_and_ship_order(request, barcode):
    print("\n========== [SCAN & SHIP DEBUG START] ==========")
    print(f"📦 Scanned Barcode: {barcode}")
    user = request.user
    print(f"👤 Logged-in User: {user}")

    disable_invoice_sync()   # ⛔ turn off invoice triggers

    try:

        # === Step 0: Locate order ===
        try:
            order = SalesOrder.objects.get(reference=barcode)
            print(f"✅ Order Found: {order.reference}")
            print(f"   → Status: {order.get_status_display()}")
            print(f"   → Customer: {getattr(order.customer, 'name', 'N/A')}")
            print(f"   → Lines Count: {order.lines.count()}")
        except SalesOrder.DoesNotExist:
            print("❌ Order not found in database.")
            print("========== [SCAN & SHIP DEBUG END] ==========")
            
            record_scan(barcode, None, None, user, "error", f"Order {barcode} not found.", [])
            return Response({
                "status": "error",
                "message": f"Order {barcode} not found.",
                "errors": ["Order not found in system."]
            }, status=status.HTTP_404_NOT_FOUND)

        # === Step 1: Skip if already shipped ===
        if order.status >= 20:
            print(f"⚠️ Order {order.reference} already shipped or completed. (status={order.status})")
            print("========== [SCAN & SHIP DEBUG END] ==========")
            
            record_scan(barcode, order, None, user, "warning", f"Order {order.reference} already shipped or completed.", [])
            return Response({
                "status": "warning",
                "message": f"Order {order.reference} already shipped or completed.",
                "order_status": order.get_status_display()
            }, status=status.HTTP_400_BAD_REQUEST)

        allocation_errors = []
        shipment_errors = []
        debug_log = []

        # === Step 2: Begin atomic transaction ===
        print("\n🔒 Starting transaction...")
        with transaction.atomic():
            lines = order.lines.all()
            print(f"🧾 Processing {lines.count()} line(s) for order {order.reference}")
            debug_log.append(f"Processing {lines.count()} order line(s)")

            # === Step 3: Allocate available stock ===
            for line in lines:
                part = line.part
                part_code = getattr(part, "IPN", None) or getattr(part, "name", "UnknownPart")
                required_qty = float(line.quantity - line.shipped)

                print(f"\n➡️ Line {line.pk}: {part_code}")
                print(f"   Required Qty: {required_qty}")
                print(f"   Already Shipped: {line.shipped}")

                if required_qty <= 0:
                    print("   ✅ Line fully shipped, skipping allocation.")
                    continue

                available_stock = StockItem.objects.filter(
                    part=part,
                    quantity__gte=required_qty,
                    sales_order=None
                ).first()

                if not available_stock:
                    msg = f"Not enough stock available for {part_code}"
                    print(f"   ❌ {msg}")
                    allocation_errors.append(msg)
                    continue

                print(f"   ✅ Found StockItem #{available_stock.pk}")
                alloc_kwargs = dict(line=line, item=available_stock, quantity=required_qty)
                alloc_fields = [f.name for f in SalesOrderAllocation._meta.get_fields()]

                if 'user' in alloc_fields:
                    alloc_kwargs['user'] = user
                elif 'created_by' in alloc_fields:
                    alloc_kwargs['created_by'] = user

                allocation = SalesOrderAllocation.objects.create(**alloc_kwargs)
                print(f"   ✅ Allocation created → ID: {allocation.pk}")
                debug_log.append(f"Allocated {required_qty}x {part_code}")

            if allocation_errors:
                print("\n⚠️ Allocation Errors Found:")
                for err in allocation_errors:
                    print(f"   → {err}")
                print("⛔ Transaction rolled back due to allocation failure.")
                print("========== [SCAN & SHIP DEBUG END] ==========")
                
                record_scan(barcode, order, None, user, "partial_error", "Allocation or shipment issue.", debug_log)
                return Response({
                    "status": "partial_error",
                    "message": "Allocation failed for one or more items.",
                    "errors": allocation_errors,
                    "log": debug_log
                }, status=status.HTTP_207_MULTI_STATUS)

            # === Step 4: Find or create shipment ===
            existing_shipment = SalesOrderShipment.objects.filter(order=order, shipment_date__isnull=True).first()
            unshipped_allocs = SalesOrderAllocation.objects.filter(line__order=order, shipment=None)

            if unshipped_allocs.exists():
                if existing_shipment:
                    shipment = existing_shipment
                    print(f"📦 Using existing open shipment: {shipment.reference}")
                else:
                    # 🔢 Count existing shipments for this order
                    existing_count = SalesOrderShipment.objects.filter(order=order).count()
                    next_number = existing_count + 1

                    # 🧾 Try to fetch the first shipment (to reuse invoice number and company)
                    first_shipment = (
                        SalesOrderShipment.objects.filter(order=order)
                        .exclude(invoice_number__isnull=True)
                        .exclude(invoice_number__exact="")
                        .order_by("id")
                        .first()
                    )

                    first_invoice_number = getattr(first_shipment, "invoice_number", None)
                    first_company = getattr(first_shipment, "courier_company_id", None)

                    print(f"📄 Found first shipment invoice: {first_invoice_number}")
                    print(f"🏢 Found first shipment company: {first_company}")

                    # 🆕 Create new reference (just sequential number)
                    shipment_ref = str(next_number)
                    print(f"\n📦 Creating new Shipment: {shipment_ref}")

                    shipment = SalesOrderShipment.objects.create(
                        order=order,
                        reference=shipment_ref,
                        notes="Auto-created via scan_and_ship_order",
                        checked_by=user,
                        invoice_number=first_invoice_number,  # Reuse first shipment invoice number if exists
                        courier_company_id=first_company,  # Reuse company from first shipment
                    )

                    print(f"✅ Shipment Created: {shipment.reference} "
                        f"(Invoice: {shipment.invoice_number}, Company: {shipment.courier_company_id})")

                # 🔗 Link unshipped allocations
                print(f"🔗 Linking {unshipped_allocs.count()} allocations to shipment {shipment.reference}")
                for alloc in unshipped_allocs:
                    try:
                        alloc.shipment = shipment
                        alloc.save()
                        print(f"   🚚 Linked Allocation #{alloc.pk}")
                    except Exception as e:
                        msg = f"Failed to link allocation #{alloc.pk}: {str(e)}"
                        print(f"   ❌ {msg}")
                        shipment_errors.append(msg)

            else:
                print("⚠️ No unshipped allocations found.")
                shipment = None

            # === Step 5: Complete shipment ===
            if shipment and not shipment_errors:
                print(f"\n📦 Completing shipment {shipment.reference}...")
                try:
                    if hasattr(shipment, "complete_shipment"):
                        shipment.complete_shipment(user)
                        shipment.refresh_from_db()
                        order.refresh_from_db()
                        print(f"✅ Shipment {shipment.reference} completed.")
                        # === Step 5.1: Trigger email after shipment completion ===
                        try:
                            from django.test import RequestFactory
                            from django.http import JsonResponse
                            import json

                            print("📧 Preparing to send shipment email...")

                            # Build the fake POST request for send_shipment_email()
                            factory = RequestFactory()

                            # Collect part details for the email payload
                            part_details = []
                            for line in order.lines.all(): 
                                # print(f"\n🧩 Line Object (ID={line.pk}):")
                                # # Convert model fields to dict and print key–value pairs
                                # for field in line._meta.get_fields():
                                #     try:
                                #         value = getattr(line, field.name)
                                #         print(f"   {field.name}: {value}")
                                #     except Exception as e:
                                #         print(f"   {field.name}: <Error reading field: {e}>")

                                # print line key and value 
                                part_details.append({
                                    "quantity": float(line.quantity),
                                    "sale_price": float(getattr(line.sale_price, "amount", line.sale_price or 0)),
                                    "part_detail": {
                                        "name": line.part.name or getattr(line.part, "IPN", None) or "UnknownPart",
                                        "description": getattr(line.part, "description", ""),
                                        "image": getattr(line.part, "get_image_url", lambda: "")() if hasattr(line.part, "get_image_url") else ""
                                    }
                                })

                            email_payload = {
                                "name": getattr(order.customer, "name", None) or getattr(order.customer, "individual_name", "Customer"),
                                "email": getattr(order.customer, "email", None),
                                "tracking_number": shipment.tracking_number,
                                "order_id": order.id,
                                "courier_company_detail": {
                                    "name": getattr(shipment.courier_company, "company_name", None),
                                    "website": getattr(shipment.courier_company, "website", None),
                                    "tracking_link": getattr(shipment.courier_company, "tracking_link", None),
                                    
                                },
                                "invoice_id": getattr(shipment, "invoice_number", None),
                                "attach_invoice": True,
                                "invoice_number": getattr(shipment, "invoice_number", None),
                                "part_details": part_details
                            }

                            # 🚀 Send asynchronously
                            print("📨 Sending shipment email asynchronously...")

                            # Run email in background thread
                            threading.Thread(
                                target=async_send_shipment_email,
                                args=(email_payload,)
                            ).start()
 
                            print("🚀 Email task started in background, not blocking scan-and-ship.")

                        except Exception as e:
                            print(f"❌ Error sending shipment email: {str(e)}")

                    else:
                        print(f"⚠️ complete_shipment() not found — leaving shipment open.")
                except Exception as e:
                    msg = f"Shipment completion failed: {str(e)}"
                    print(f"❌ {msg}")
                    shipment_errors.append(msg)

            if shipment_errors:
                print("\n⚠️ Shipment Errors Found:")
                for err in shipment_errors:
                    print(f"   → {err}")
                print("========== [SCAN & SHIP DEBUG END] ==========")
                record_scan(barcode, order, shipment, user, "partial_error", "Shipment completed with some errors.", debug_log)
                return Response({
                    "status": "partial_error",
                    "message": "Shipment completed with some errors.",
                    "errors": shipment_errors,
                    "log": debug_log
                }, status=status.HTTP_207_MULTI_STATUS)

            # === Step 6: Update order status manually ===
            if order.status < 15:
                order.status = 15
                order.save()
                print("🔄 Order marked as 'In Progress'")

            if all(line.shipped >= line.quantity for line in order.lines.all()):
                order.status = 20
                order.save()
                print("🚀 Order marked as 'Shipped'")

        # === Step 7: Final Response ===
        print("\n✅ All steps executed successfully.")
        print(f"📄 Order {order.reference} fully processed.")
        print("========== [SCAN & SHIP DEBUG END] ==========")
        
        record_scan(barcode, order, shipment, user, "success", f"Order {order.reference} shipped successfully.", debug_log)
        return Response({
            "status": "success",
            "message": f"Order {order.reference} allocated and shipped successfully.",
            "data": {
                "order_reference": order.reference,
                "order_status": order.get_status_display(),
                "shipment_reference": getattr(shipment, "reference", None),
                "lines": order.lines.count()
            },
            "log": debug_log
        }, status=status.HTTP_200_OK)

    finally:
        enable_invoice_sync()   # ✅ enable invoice sync again

import threading, json
from django.test import RequestFactory

def async_send_shipment_email(payload):
    try:
        print("📧 Starting async email send...")

        factory = RequestFactory()
        req = factory.post(
            "/api/send_shipment_email/",
            data=json.dumps(payload),
            content_type="application/json"
        )

        send_shipment_email(req)
        print("📩 Shipment email sent successfully (async)")
    except Exception as e:
        print("❌ Async email error:", e)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def scan_history_list(request):
    print("\n========== [SCAN HISTORY API DEBUG START] ==========")
    print(f"👤 User: {request.user}")
    print(f"📡 Query Params: {request.query_params}")

    # Base queryset
    history = SalesOrderScanHistory.objects.all().select_related('order', 'shipment', 'user')

    # === FILTERS ===
    search_query = request.query_params.get('search')
    status_filter = request.query_params.get('status')
    created_after = request.query_params.get('created_after')
    created_before = request.query_params.get('created_before')

    # Apply search (barcode or order reference)
    if search_query:
        print(f"🔍 Applying search filter: {search_query}")
        history = history.filter(
            Q(barcode__icontains=search_query) |
            Q(order__reference__icontains=search_query)
        )

    # Filter by status
    if status_filter:
        print(f"⚙️ Filtering by status: {status_filter}")
        history = history.filter(status=status_filter)

    # Date range filters
    if created_after:
        start_date = parse_date(created_after)
        if start_date:
            print(f"📅 Filtering records created after: {start_date}")
            history = history.filter(created_at__date__gte=start_date)

    if created_before:
        end_date = parse_date(created_before)
        if end_date:
            print(f"📅 Filtering records created before: {end_date}")
            history = history.filter(created_at__date__lte=end_date)

    # Limit and order results
    history = history.order_by('-created_at')[:200]

    print(f"📊 Final queryset count: {history.count()}")
    print("========== [SCAN HISTORY API DEBUG END] ==========\n")

    # Serialize output
    data = [
        {
            "id": h.id,
            "barcode": h.barcode,
            "order_reference": getattr(h.order, "reference", None),
            "shipment_reference": getattr(h.shipment, "reference", None),
            "status": h.status,
            "message": h.message,
            "user": getattr(h.user, "username", None),
            "created_at": h.created_at,
        }
        for h in history
    ]

    return Response(data)








class SalesOrderGenerateDTDC(APIView):
    """
    Generate DTDC consignment AWB numbers for one or multiple Sales Orders.
    Fetches customer name, address (like label builder), and saves tracking details
    in SalesOrderShipment (just like invoice numbers are stored).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        import json, traceback
        from django.http import JsonResponse

        order_ids = request.data.get("order_ids", [])
        print("📦 Received order_ids:", order_ids)

        if not order_ids:
            return Response({"success": False, "error": "No order IDs provided"}, status=400)

        created_shipments, errors = [], []

        for order_id in order_ids:
            try:
                print(f"\n🔹 Processing Sales Order ID: {order_id}")
                order = models.SalesOrder.objects.get(pk=order_id)
                print(f"   ➤ Order Reference: {order.reference}")
                
                # ---------------- Check Shipment Status ----------------
                existing_shipment = models.SalesOrderShipment.objects.filter(order=order).first()

                if existing_shipment:
                    # If tracking number exists, check its status through DTDC API
                    tracking_response = self.get_shipment_tracking(existing_shipment.tracking_number)
                    print(f"   🚚 Found tracking info: {tracking_response}")
                    
                    # If the shipment is not in a final state (e.g., "Delivered"), skip creating a new shipment
                    if tracking_response['status'] in ['pickup_scheduled', 'in_transit', 'out_for_delivery', 'not_delivered']:
                        print(f"⚠️ Skipping AWB creation for Order {order.reference} — Status: {tracking_response['status']}")
                        created_shipments.append({
                            "order_id": order.id,
                            "reference": order.reference,
                            "tracking_number": existing_shipment.tracking_number,
                            "courier": existing_shipment.courier_company.company_name,
                        })
                        continue  # Skip to the next order as no new AWB is generated
                    else:
                        print(f"⚠️ Existing shipment is in a final state ({tracking_response['status']}) — Proceeding to create a new shipment.")
                else:
                    print(f"   No existing shipment found for Order {order.reference}. Proceeding to generate a new AWB.")
                    
                # ---------------- Customer Name Logic ----------------
                cust = getattr(order, "customer", None)
                is_obj = hasattr(cust, "primary_address")
                addr = getattr(order, "shipping_address", None) or (cust.primary_address if is_obj else None)

                country = getattr(addr, "country", None)
                province = getattr(addr, "province", None)

                print(f"   🌍 Country: {country}, 🏙️ Province: {province}")

                # Proceed only for valid region (India, excluding Gujarat)
                country_str = str(country).strip().lower()
                province_str = str(province).strip().lower()

                if country_str != "india":
                    print(f"⚠️ Skipping order {order.reference} — International order (not India).")
                    errors.append({
                        "order_id": order_id,
                        "error": "Skipped: Only Indian orders are allowed for DTDC."
                    })
                    continue

                individual_name = getattr(cust, "individual_name", "") or ""
                company_name = getattr(cust, "name", "") or ""

                if individual_name and company_name:
                    full_name = f"{individual_name} ({company_name})"
                elif individual_name:
                    full_name = individual_name
                elif company_name:
                    full_name = company_name
                else:
                    full_name = str(cust) or "Unknown Customer"

                print(f"   👤 Full Recipient Name: {full_name}")

                # ---------------- Address Logic (like label) ----------------
                addr_lines = [full_name, addr.line1, addr.line2 or "", f"{addr.postal_code} {addr.postal_city}".strip(), country]

                print(f"   🏠 Address lines: {addr_lines}")

                # ---------------- Contact Info ----------------
                def first_nonempty(*vals):
                    return next((v for v in vals if v), "")

                contact = getattr(order, "contact", None)
                phone_raw = first_nonempty(
                    getattr(contact, "phone", None) if contact else None,
                    getattr(cust, "phone", None),
                    getattr(addr, "phone", None),
                )
                email_raw = first_nonempty(
                    getattr(contact, "email", None) if contact else None,
                    getattr(cust, "email", None),
                    getattr(addr, "email", None),
                )

                phone = phone_raw.strip() if phone_raw else "9999999999"
                email = email_raw.strip().lower() if email_raw else ""

                print(f"   📞 Phone: {phone}")
                print(f"   📧 Email: {email}")

                # ---------------- Declared Value ----------------
                declared_value = order.total_price.amount if hasattr(order.total_price, "amount") else order.total_price
                declared_value = float(declared_value or 0)
                print(f"   💰 Declared Value: {declared_value}")

                # ---------------- Prepare Line Items ----------------
                pieces_details = []
                total_weight = 0.0
                
                for line_item in order.lines.all():
                    piece_weight = 0.5  # Default weight per piece
                    total_weight += piece_weight
                    
                    line_price = line_item.total_line_price
                    price_value = float(line_price.amount) if hasattr(line_price, "amount") else float(str(line_price).replace("₹", "").replace(",", "").strip())
                    
                    piece = {
                        "description": line_item.part.description if line_item.part else "Sales Order Item",
                        "declared_value": str(price_value),
                        "weight": piece_weight,
                        "height": 5,
                        "length": 10,
                        "width": 15
                    }
                    pieces_details.append(piece)
                    
                print(f"   📦 Total Pieces: {len(pieces_details)}")

                # ---------------- Build Payload ----------------
                payload = {
                    "consignments": [
                        {
                            "customer_code": "AO4896",
                            "service_type_id": "B2C PRIORITY",
                            "load_type": "NON-DOCUMENT",
                            "description": order.description or "Sales Order Dispatch",
                            "consignment_type": "FORWARD",
                            "commodity_id": "General Goods",
                            "customer_reference_number": str(order.reference),
                            "declared_value": declared_value,
                            "dimension_unit": "cm",
                            "length": 10,
                            "width": 15,
                            "height": 5,
                            "weight_unit": "kg",
                            "weight": total_weight,
                            "num_pieces": str(len(pieces_details)),
                            "origin_details": {
                                "name": "Vicharak Warehouse",
                                "phone": "+919773432774",
                                "address_line_1": "OFFICE NO. T-18, THIRD FLOOR, SHREE NILKANTH BUSINESS HUB, SINGANPORE, CAUSEWAY ROAD",
                                "pincode": 395004,
                                "city": "Surat",
                                "state": "Gujarat"
                            },
                            "destination_details": {
                                "name": full_name,
                                "phone": phone_raw,
                                "address_line_1": addr.line1,
                                "address_line_2": addr.line2 or "",
                                "pincode": addr.postal_code,
                                "city": addr.postal_city,
                                "state": addr.province,
                            },
                            "pieces_detail": pieces_details,
                        }
                    ]
                }

                print("📤 Sending payload to DTDC API:")
                print(json.dumps(payload, indent=2))

                # Sending to the API
                headers = {"Content-Type": "application/json", "api-key": "ff80cd3ece4fb2c2908530f75eb091"}
                response = requests.post("https://dtdcapi.shipsy.io/api/customer/integration/consignment/softdata", headers=headers, data=json.dumps(payload), timeout=30)

                print(f"📨 DTDC API Response Status: {response.status_code}")
                print(f"📨 DTDC API Response Body: {response.text}")

                if response.status_code != 200:
                    errors.append({
                        "order_id": order_id,
                        "error": f"DTDC API Error: {response.status_code} {response.text}"
                    })
                    continue

                res_data = response.json()
                awb_number = res_data["data"][0]["reference_number"]
                print(f"   🚚 Received AWB Number: {awb_number}")

                # ---------------- Save Tracking Info ----------------
                shipment, _ = models.SalesOrderShipment.objects.get_or_create(order=order)
                shipment.tracking_number = awb_number
                shipment.shipment_date = None  # Keep as pending

                # auto-create or fetch courier
                courier, _ = models.CourierCompany.objects.get_or_create(company_name="DTDC", defaults={"website": "https://www.dtdc.in", "tracking_link": "https://www.dtdc.com/in/"})
                shipment.courier_company = courier

                shipment.save(update_fields=["tracking_number", "courier_company", "shipment_date"])
                print(f"✅ Saved Shipment → Order: {order.reference}, AWB: {awb_number}, Shipment Date: {shipment.shipment_date}")

                created_shipments.append({
                    "order_id": order.id,
                    "reference": order.reference,
                    "tracking_number": shipment.tracking_number,
                    "courier": courier.company_name,
                })

            except Exception as e:
                tb = traceback.format_exc()
                print(f"💥 Error processing order {order_id}: {e}\n{tb}")
                errors.append({"order_id": order_id, "error": str(e)})

        # ---------------- Summary + Response ----------------
        print("\n✅ Summary:")
        print(f"   Successful Shipments: {len(created_shipments)}")
        print(f"   Errors: {len(errors)}")

        return Response({
            "success": len(created_shipments) > 0,
            "created_shipments": created_shipments,
            "errors": errors
        })

    def get_shipment_tracking(self, tracking_number):
        """Helper function to fetch shipment tracking details from the API."""
        url = f"https://dtdcapi.shipsy.io/api/customer/integration/consignment/track?reference_number={tracking_number}"
        headers = {"api-key": "ff80cd3ece4fb2c2908530f75eb091"}

        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
        else:
            return {"status": "error", "message": "Failed to fetch tracking info"}

from django.http import HttpResponse, JsonResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT
from io import BytesIO
from datetime import datetime
import urllib.request
import traceback
from order import models
from num2words import num2words

class SalesOrderGenerateInvoice(APIView):
    """
    Generate PDF invoices for one or multiple Sales Orders.
    For international orders (country != India):
      - Item name fixed to "Shrike-lite PCB Sample Free 0.4$ Rate."
      - Rate $0.40 per pcs, amount = qty * 0.40
      - No IGST and No shipping charge
      - Currency in $
    """

    permission_classes = [IsAuthenticated]

    # ---------- helper to load logo from URL (class method, not nested) ----------
    def _logo_flowable_from_url(self, url, max_w=40*mm, max_h=25*mm):
        """
        Load logo from URL or fall back to spacer.
        Supports HTTPS with relaxed SSL and User-Agent header.
        """
        import ssl
        import urllib.request
        from io import BytesIO
        from reportlab.platypus import Image, Spacer

        try:
            ssl_ctx = ssl._create_unverified_context()
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (ReportLab PDF Generator)"}
            )
            with urllib.request.urlopen(req, context=ssl_ctx, timeout=10) as resp:
                img_data = resp.read()
            if not img_data:
                raise ValueError("Empty image data")
            buf = BytesIO(img_data)
            img = Image(buf)
            img._restrictSize(max_w, max_h)
            print(f"✅ Logo loaded successfully from {url} ({len(img_data)} bytes)")
            return img
        except Exception as e:
            print(f"❌ Logo load failed: {e}")
            return Spacer(1, 1)

    def post(self, request, *args, **kwargs):
        """
        Generate and return a single merged PDF of all selected invoices.
        """
        order_ids = request.data.get("order_ids", [])
        print("📄 Received order_ids for batch invoice generation:", order_ids)

        if not order_ids:
            return Response({"success": False, "error": "No order IDs provided"}, status=400)

        merger = PdfMerger()
        generated = []
        errors = []

        for oid in order_ids:
            try:
                order = models.SalesOrder.objects.get(pk=oid)
                print(f"🧾 Generating invoice for order {order.reference}...")
                invoice_data = self.prepare_invoice_data(order)
                pdf_buf = self.generate_invoice_pdf(invoice_data)

                merger.append(pdf_buf)  # ✅ merge each PDF buffer
                generated.append(order.reference)

            except Exception as e:
                print(f"❌ Failed for order {oid}: {e}")
                errors.append({"order_id": oid, "error": str(e)})

        if not generated:
            return Response({"success": False, "error": "No invoices generated", "errors": errors}, status=500)

        # Merge complete
        output_buf = BytesIO()
        merger.write(output_buf)
        merger.close()
        output_buf.seek(0)

        filename = f"invoices_batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

        response = HttpResponse(output_buf.getvalue(), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'

        print(f"✅ Combined invoice PDF created for {len(generated)} orders")
        return response
    
    def get(self, request, *args, **kwargs):
        """
        Download a single invoice PDF.
        URL: /api/so/generate-invoice/?order_id=123
        """
        order_id = request.GET.get("order_id")

        if not order_id:
            return JsonResponse({"error": "order_id parameter required"}, status=400)

        try:
            order = models.SalesOrder.objects.get(pk=order_id)
            invoice_data = self.prepare_invoice_data(order)
            pdf_buffer = self.generate_invoice_pdf(invoice_data)
            if not pdf_buffer:
                raise RuntimeError("PDF buffer is empty")

            response = HttpResponse(pdf_buffer.getvalue(), content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="invoice_{order.reference}.pdf"'

            print(f"✅ Invoice PDF downloaded for Order {order.reference}")
            return response

        except models.SalesOrder.DoesNotExist:
            return JsonResponse({"error": f"Sales Order {order_id} not found"}, status=404)
        except Exception as e:
            tb = traceback.format_exc()
            print(f"💥 Error: {e}\n{tb}")
            return JsonResponse({"error": str(e)}, status=500)

    def prepare_invoice_data(self, order):
        print(f"   📋 Preparing invoice data for Order: {order.reference}")

        # ---------------- Fetch Invoice Number & Date from SalesOrderShipment ----------------
        try:
            shipment = order.shipments.first()  # Get the first shipment
            if shipment:
                # Use invoice_number field from shipment, fallback to shipment reference, then order reference
                invoice_number = shipment.invoice_number or shipment.reference or order.reference
                
                # Use shipment_date for invoice date
                if shipment.shipment_date:
                    invoice_date = shipment.shipment_date.strftime('%d-%b-%Y')
                elif order.creation_date:
                    invoice_date = order.creation_date.strftime('%d-%b-%Y')
                else:
                    invoice_date = 'N/A'
                
                print(f"   📦 Shipment: {shipment.reference}, Invoice#: {invoice_number}, Date: {invoice_date}")
            else:
                # Fallback to order reference if no shipment exists
                invoice_number = order.reference
                invoice_date = order.creation_date.strftime('%d-%b-%Y') if order.creation_date else 'N/A'
                print(f"   ⚠️ No shipment found, using order data: {invoice_number}, Date: {invoice_date}")
        except Exception as e:
            print(f"   ❌ Error fetching shipment: {e}")
            invoice_number = order.reference
            invoice_date = order.creation_date.strftime('%d-%b-%Y') if order.creation_date else 'N/A'

        # ---------------- Company Details ----------------
        company_data = {
            'name': 'Vicharak',
            'address': 'PL 44, GR FL MARUTI IND-1, AT LASKANA, KAMREJ, Laskana',
            'city': 'Surat Gujarat 395004',
            'country': 'India',
            'phone': '9727813180',
            'email': 'sales@vicharak.in',
            'website': 'https://vicharak.in/',
            'gstin': '24AAJCV8134E1ZB',
        }

        # ---------------- Customer Details ----------------
        cust = getattr(order, "customer", None)
        if not cust:
            print(f"❌ Customer not found for order {order.reference}")
            return None

        is_obj = hasattr(cust, "primary_address")

        individual_name = getattr(cust, "individual_name", "") or ""
        company_name = getattr(cust, "name", "") or ""

        if individual_name and company_name:
            full_name = f"{individual_name} ({company_name})"
        elif individual_name:
            full_name = individual_name
        elif company_name:
            full_name = company_name
        else:
            full_name = str(cust) or "Unknown Customer"

        print(f"   👤 Customer Name: {full_name}")

        # ---------------- Address Details ----------------
        addr = getattr(order, "shipping_address", None) or (cust.primary_address if is_obj else None)

        if addr:
            bill_to_data = {
                'name': full_name,
                'address': getattr(addr, "line1", ""),
                'address_line2': getattr(addr, "line2", ""),
                'city': getattr(addr, "postal_city", ""),
                'pincode': getattr(addr, "postal_code", ""),
                'state': getattr(addr, "province", ""),
                'country': getattr(addr.country, "name", str(addr.country)) if addr.country else "India",
            }

            ship_to_data = {
                'address': getattr(addr, "line1", ""),
                'address_line2': getattr(addr, "line2", ""),
                'city': getattr(addr, "postal_city", ""),
                'pincode': getattr(addr, "postal_code", ""),
                'state': getattr(addr, "province", ""),
                'country': getattr(addr.country, "name", str(addr.country)) if addr.country else "India"
            }
        else:
            print(f"❌ Shipping address not found for order {order.reference}")
            return None

        # ---------------- Contact Info ----------------
        def first_nonempty(*vals):
            return next((v for v in vals if v), "")

        contact = getattr(order, "contact", None)
        phone_raw = first_nonempty(
            getattr(contact, "phone", None) if contact else None,
            getattr(cust, "phone", None),
            getattr(addr, "phone", None) if addr else None,
        )
        email_raw = first_nonempty(
            getattr(contact, "email", None) if contact else None,
            getattr(cust, "email", None),
            getattr(addr, "email", None) if addr else None,
        )

        phone = phone_raw.strip() if phone_raw else "N/A"
        email = email_raw.strip().lower() if email_raw else "N/A"

        print(f"   📞 Phone: {phone}, 📧 Email: {email}")

        # ---------------- Determine if International ----------------
        ship_country = (bill_to_data.get('country') or '').strip()
        is_international = ship_country.lower() != 'india'
        ship_state = (bill_to_data.get('state') or '').strip().lower()

        is_gujarat = (ship_state == 'gujarat')

        # ---------------- Line Items + Currency / International ----------------
        items = []
        subtotal = 0.0
        
        # Always define GST totals to avoid missing-variable errors
        cgst_total = 0.0
        sgst_total = 0.0
        igst_total = 0.0
        shipping = 0.0
        shipping_base = 0.0
        shipping_gst = 0.0
        currency_symbol = '₹'

        if is_international:
            # 🌍 INTERNATIONAL ORDER LOGIC
            FIXED_NAME = "Shrike-lite PCB Sample Free 0.4$ Rate."
            FIXED_RATE = 0.40  # USD per pcs

            for line_item in order.lines.all() or []:
                qty = float(line_item.quantity or 1)
                amount = round(qty * FIXED_RATE, 2)

                items.append({
                    'name': FIXED_NAME,
                    'description': FIXED_NAME,  # Use fixed name as description too
                    'hsn': '84715000',
                    'qty': qty,
                    'unit': 'pcs',
                    'rate': FIXED_RATE,
                    'amount': amount,
                })
                subtotal += amount

            # No GST, No Shipping for international orders
            igst_total = 0.0
            shipping = 0.0
            shipping_base = 0.0
            shipping_gst = 0.0
            total = subtotal

            currency_symbol = '$'

            print(f"   🌍 International invoice: {ship_country}")
            print(f"   💰 Subtotal: ${subtotal:.2f}, Total: ${total:.2f}")

        else:
            # 🇮🇳 DOMESTIC (INDIA) ORDER LOGIC
            for line_item in order.lines.all() or []:
                line_price = line_item.total_line_price

                if hasattr(line_price, "amount"):
                    total_incl_gst = float(line_price.amount)
                else:
                    price_str = str(line_price).replace("₹", "").replace(",", "").strip()
                    try:
                        total_incl_gst = float(price_str)
                    except:
                        total_incl_gst = 0.0

                qty = float(line_item.quantity or 1)
                inclusive_unit_price = round(total_incl_gst / qty, 2)
                
                if is_gujarat:
                    cgst_rate = 9.0
                    sgst_rate = 9.0
                    igst_rate = 0.0
                else:
                    cgst_rate = 0.0
                    sgst_rate = 0.0
                    igst_rate = 18.0

                # Exclusive price
                exclusive_unit_price = round(inclusive_unit_price / (1 + (cgst_rate + sgst_rate + igst_rate) / 100), 2)

                # GST per unit
                cgst_amount_per_unit = round(exclusive_unit_price * (cgst_rate / 100), 2)
                sgst_amount_per_unit = round(exclusive_unit_price * (sgst_rate / 100), 2)
                igst_amount_per_unit = round(exclusive_unit_price * (igst_rate / 100), 2)

                # Total GST per line
                total_cgst = cgst_amount_per_unit * qty
                total_sgst = sgst_amount_per_unit * qty
                total_igst = igst_amount_per_unit * qty
                amount_inclusive = round(inclusive_unit_price * qty, 2)

                item_data = {
                    'name': line_item.part.name if line_item.part else "Item",
                    'description': line_item.part.description if line_item.part else "Sales Order Item",
                    'hsn': '84715000',
                    'qty': qty,
                    'unit': 'pcs',
                    'rate': exclusive_unit_price,
                    'amount': round(exclusive_unit_price * qty, 2),
                    'amount_incl_gst': amount_inclusive,
                    'cgst_rate': cgst_rate,
                    'sgst_rate': sgst_rate,
                    'igst_rate': igst_rate,
                    'cgst_amount': total_cgst,
                    'sgst_amount': total_sgst,
                    'igst_amount': total_igst,
                }


                items.append(item_data)
                subtotal += item_data['amount_incl_gst']

            cgst_total = sum(item.get('cgst_amount', 0.0) for item in items)
            sgst_total = sum(item.get('sgst_amount', 0.0) for item in items)
            igst_total = sum(item.get('igst_amount', 0.0) for item in items)

            # Fetch WooCommerce Shipping
            try:
                shipping = float(get_wordpress_shipping_charge(order.wordpress_order_id))
                shipping_gst_rate = 18.0
                shipping_base = round(shipping / (1 + shipping_gst_rate / 100), 2)
                shipping_gst = round(shipping - shipping_base, 2)
                print(f"   🚚 WooCommerce Shipping Charge: ₹{shipping}")
            except Exception as e:
                print(f"   ⚠️ Error fetching WooCommerce shipping: {e}")
                shipping = 0.0
                shipping_base = 0.0
                shipping_gst = 0.0

            total = subtotal + shipping_base + shipping_gst
            currency_symbol = '₹'

            print(f"   💰 Subtotal: ₹{subtotal:.2f}, IGST: ₹{igst_total:.2f}, Shipping: ₹{shipping:.2f}, Total: ₹{total:.2f}")

        # ---------------- Build Final Invoice Data ----------------
        invoice_data = {
            'invoice_number': invoice_number,
            'invoice_date': invoice_date,
            'company': company_data,
            'bill_to': bill_to_data,
            'ship_to': ship_to_data,
            'contact': {
                'phone': phone,
                'email': email,
            },
            'place_of_supply': ship_to_data['state'] or ship_to_data['country'],
            'items': items,
            'subtotal': round(subtotal, 2),
            'igst_total': round(igst_total, 2),
            'shipping': round(shipping, 2),
            'shipping_base': round(shipping_base, 2),
            'shipping_gst': round(shipping_gst, 2),
            'total': round(total, 2),
            'currency_symbol': currency_symbol,
            'is_international': is_international,
            'in_gujarat': is_gujarat,
            'cgst_total': round(cgst_total, 2),
            'sgst_total': round(sgst_total, 2),
            'notes': 'Thank you for your business!',
        }

        print(f"   ✅ Invoice data prepared successfully")
        return invoice_data
    
    
    def generate_invoice_pdf(self, invoice_data):
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
        
        print(f"   🖨️ Generating PDF for Invoice: {invoice_data['invoice_number']}")

        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4,
            rightMargin=15*mm, leftMargin=15*mm,
            topMargin=5*mm, bottomMargin=25*mm
        )

        styles = getSampleStyleSheet()

        style_small = ParagraphStyle(
            'Small',
            parent=styles['Normal'],
            fontName='DejaVuSans',
            fontSize=9
        )

        style_normal = ParagraphStyle(
            'NormalUnicode',
            parent=styles['Normal'],
            fontName='DejaVuSans',
            fontSize=10
        )

        elements = []

        # ---------------- Header Section (Logo LEFT, Invoice Title RIGHT) ----------------
        from django.conf import settings
        import os
        from reportlab.platypus import Image, Spacer

        # Static local logo path
        logo_path = os.path.join(settings.STATIC_ROOT, "img", "Vicharak_logo.png")

        if os.path.exists(logo_path):
            logo = Image(logo_path)
            logo._restrictSize(50*mm, 30*mm)
            print("✅ Using static logo:", logo_path)
        else:
            print("❌ Static logo NOT found:", logo_path)
            logo = Spacer(1, 1)

        currency = invoice_data.get('currency_symbol', '₹')


        # Left side: Company Name + Logo (side by side)
        company_name_para = Paragraph(
            f"<font name='DejaVuSans-Bold' size='16'>{invoice_data['company']['name']}</font>",
            ParagraphStyle(
                'CompanyName',
                parent=style_small,
                fontName="DejaVuSans-Bold",   # 🔥 REQUIRED FIX
                fontSize=16,
                alignment=TA_LEFT,
                spaceBefore=8,
            )
        )

        left_stack = Table([[logo, company_name_para]], colWidths=[50*mm, 30*mm])
        left_stack.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),  # Center vertically
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),        # Logo left
            ('ALIGN', (1, 0), (1, 0), 'LEFT'),        # Company name right of logo
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (0, 0), 0),      # ✅ No padding on logo right
            ('LEFTPADDING', (1, 0), (1, 0), 2),       # ✅ Minimal left padding on company name (60% reduction)
            ('RIGHTPADDING', (1, 0), (1, 0), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        
        # Right side: TAX INVOICE + Invoice Number + Invoice Date
        right_header = Paragraph(
            f"<b><font size=26>TAX INVOICE</font></b><br/>"
            f"<font size=11>#{invoice_data['invoice_number']}</font><br/>"
            f"<font size=9>Invoice Date: {invoice_data['invoice_date']}</font>",
            ParagraphStyle(
                'InvoiceHeader',
                parent=style_small,
                alignment=TA_RIGHT,
                leading=18,
                spaceBefore=0,
                spaceAfter=0,
            )
        )

        # Header table with logo left and invoice details right
        header_table = Table([[left_stack, right_header]], colWidths=[90*mm, 90*mm])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 6*mm))

        # ---------------- Bill To / Ship To ----------------
        bill_to = invoice_data['bill_to']
        ship_to = invoice_data['ship_to']

        address_data = [
            [
                Paragraph(
                    f"<b>Bill To</b><br/>"
                    f"{bill_to['name']}<br/>"
                    f"{self.wrap_address(bill_to['address'])}<br/>"
                    f"{bill_to['city']}<br/>"
                    f"{bill_to['pincode']} {bill_to['state']}<br/>"
                    f"{bill_to['country']}<br/>"
                    f"<b>Phone:</b> {invoice_data['contact']['phone']}<br/>"
                    f"<b>Email:</b> {invoice_data['contact']['email']}",
                    style_small
                ),
                Paragraph(
                    f"<b>Ship To</b><br/>"
                    f"{self.wrap_address(ship_to['address'])}<br/>"
                    f"{ship_to['city']}<br/>"
                    f"{ship_to['pincode']} {ship_to['state']}<br/>"
                    f"{ship_to['country']}<br/>"
                    f"<b>Phone:</b> {invoice_data['contact']['phone']}<br/>"
                    f"<b>Email:</b> {invoice_data['contact']['email']}<br/><br/>"
                    f"<b>Place Of Supply:</b> {invoice_data['place_of_supply']}",
                    style_small
                )
            ]
        ]


        address_table = Table(
            address_data,
            colWidths=[87.5*mm, 87.5*mm]   # SAME WIDTH AS ITEM TABLE
        )

        address_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ]))

        elements.append(address_table)
        elements.append(Spacer(1, 6*mm))

        # ---------------- Items Table ----------------
        items_data = []
        if invoice_data.get('is_international'):
            items_data.append(['#', 'Item & Description', 'HSN/SAC', 'Qty', 'Rate', 'Amount'])
            for idx, item in enumerate(invoice_data['items'], 1):
                items_data.append([
                    str(idx),
                    f"{item.get('description','')}",
                    item['hsn'],
                    f"{item['qty']:.2f}\n{item['unit']}",
                    f"{currency}{item['rate']:.2f}",
                    f"{currency}{item['amount']:.2f}",
                ])
            items_table = Table(items_data, colWidths=[8*mm, 70*mm, 22*mm, 18*mm, 25*mm, 30*mm])
        else:
            if invoice_data['in_gujarat']:
                items_data.append([
                    '#', 'Item & Description', 'HSN', 'Qty',
                    'Rate', 'CGST (9%)', 'SGST (9%)', 'Amount'
                ])

                for idx, item in enumerate(invoice_data['items'], 1):
                    items_data.append([
                        str(idx),
                        f"{item.get('description', '')}",
                        item['hsn'],
                        f"{item['qty']:.2f}\n{item['unit']}",
                        f"{currency}{item['rate']:.2f}",
                        f"{currency}{item['cgst_amount']:.2f}",
                        f"{currency}{item['sgst_amount']:.2f}",
                        f"{currency}{item['amount_incl_gst']:.2f}",
                    ])

                items_table = Table(
                    items_data,
                    colWidths=[8*mm, 55*mm, 20*mm, 15*mm, 20*mm, 22*mm, 22*mm, 25*mm]
                )

            else:
                # Your existing IGST table

                items_data.append(['#', 'Item & Description', 'HSN/SAC', 'Qty', 'Rate', 'IGST(18%)', 'Amount'])
                for idx, item in enumerate(invoice_data['items'], 1):
                    items_data.append([
                        str(idx),
                        f"{item.get('description','')}",
                        item['hsn'],
                        f"{item['qty']:.2f}\n{item['unit']}",

                        # RATE (exclusive base price)
                        f"{currency}{item['rate']:.2f}",

                        # GST (18%)
                        f"{currency}{item['igst_amount']:.2f}", 

                        # AMOUNT INCLUSIVE (unit incl × qty)
                        f"{currency}{item['amount_incl_gst']:.2f}",
                    ])


                items_table = Table(items_data, colWidths=[8*mm, 60*mm, 22*mm, 18*mm, 20*mm, 22*mm, 25*mm])

        items_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#444444")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('GRID', (0, 0), (-1, -1), 0.6, colors.HexColor("#444444")),
            ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor("#444444")),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (1, 1), (1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, -1), 'DejaVuSans'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ]))
        
        elements.append(items_table)
        elements.append(Spacer(1, 5*mm))

        # ---------------- Summary Section ----------------
        if invoice_data.get('is_international'):
            summary_data = [
                ['', '', 'Sub Total', f"{currency}{invoice_data['subtotal']:.2f}"],
                ['', '', 'Total', f"{currency}{invoice_data['total']:.2f}"],
            ]
        else:
            summary_data = [
                ['', '', 'Sub Total', f"{currency}{invoice_data['subtotal']:.2f}"],
                ['', '', 'Shipping Charge', f"{currency}{invoice_data['shipping_base']:.2f}"],
                ['', '', 'Shipping GST (18%)', f"{currency}{invoice_data['shipping_gst']:.2f}"],
                ['', '', 'Total', f"{currency}{invoice_data['total']:.2f}"],
            ]


        summary_table = Table(summary_data, colWidths=[50*mm, 50*mm, 40*mm, 35*mm])
        summary_table.setStyle(TableStyle([
            ('ALIGN', (2, 0), (3, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, -1), 'DejaVuSans'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('FONTNAME', (2, -1), (3, -1), 'DejaVuSans'),
            ('FONTSIZE', (2, -1), (3, -1), 11),
            ('LINEABOVE', (2, -1), (3, -1), 1, colors.black),
            ('TOPPADDING', (2, 0), (3, -1), 4),
            ('BOTTOMPADDING', (2, 0), (3, -1), 4),
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, 3*mm))

        # ---------------- Total in Words ----------------
        elements.append(Paragraph(
            f"<b>Total In Words:</b><br/>{self.amount_to_words(invoice_data['total'], currency, invoice_data.get('is_international', False))}",
            style_small
        ))
        elements.append(Spacer(1, 3*mm))

        # ---------------- Notes ----------------
        elements.append(Paragraph(f"<b>Note</b><br/>{invoice_data['notes']}", style_small))

        # ---------------- FOOTER with Company Details ----------------
        def add_footer(canvas, doc):
            canvas.saveState()
            
            # Footer positioned at bottom
            footer_y = 20*mm
            
            # Company details in footer (centered)
            footer_text = (
                # f"{invoice_data['company']['name']}\n"
                f"{invoice_data['company']['address']}, {invoice_data['company']['city']}, {invoice_data['company']['country']}\n"
                f"Email: {invoice_data['company']['email']} | Website: {invoice_data['company']['website']} | Contact: {invoice_data['company']['phone']}\n"
                # f"GSTIN: {invoice_data['company']['gstin']}"
            )
            
            # Draw footer text centered
            text_object = canvas.beginText()
            text_object.setTextOrigin(A4[0]/2, footer_y)
            text_object.setFont('DejaVuSans', 8)
            
            # Center align each line
            for line in footer_text.split('\n'):
                text_width = canvas.stringWidth(line, 'DejaVuSans', 8)
                text_object.setTextOrigin((A4[0] - text_width) / 2, text_object.getY())
                text_object.textLine(line)
            
            canvas.drawText(text_object)
            canvas.restoreState()

        # Build PDF with footer
        doc.build(elements, onFirstPage=add_footer, onLaterPages=add_footer)
        buffer.seek(0)
        print(f"   ✅ PDF generated successfully")
        save_dir = os.path.join(settings.MEDIA_ROOT, "so_files")
        os.makedirs(save_dir, exist_ok=True)

        file_path = os.path.join(
            save_dir,
            f"invoice_{invoice_data['invoice_number']}.pdf"
        )

        with open(file_path, "wb") as f:
            f.write(buffer.getvalue())

        print("📁 Invoice saved at:", file_path)
        return buffer

    def amount_to_words(self, amount, currency_symbol='₹', is_international=False):
        whole = int(round(amount))

        # Convert number → words (English, title case off)
        words = num2words(whole, lang='en').replace("-", " ")

        if is_international:
            return f"{words.capitalize()} US Dollars Only"

        return f"{words.capitalize()} Indian Rupees Only"

    def wrap_address(self, text, limit=40):
        if not text:
            return ""
        return "<br/>".join(text[i:i+limit] for i in range(0, len(text), limit))



order_api_urls = [
    # API endpoints for purchase orders
    path(
        'po/',
        include([
            # Individual purchase order detail URLs
            path(
                '<int:pk>/',
                include([
                    path(
                        'cancel/', PurchaseOrderCancel.as_view(), name='api-po-cancel'
                    ),
                    path('hold/', PurchaseOrderHold.as_view(), name='api-po-hold'),
                    path(
                        'complete/',
                        PurchaseOrderComplete.as_view(),
                        name='api-po-complete',
                    ),
                    path('issue/', PurchaseOrderIssue.as_view(), name='api-po-issue'),
                    path(
                        'metadata/',
                        MetadataView.as_view(model=models.PurchaseOrder),
                        name='api-po-metadata',
                    ),
                    path(
                        'receive/',
                        PurchaseOrderReceive.as_view(),
                        name='api-po-receive',
                    ),
                    # PurchaseOrder detail API endpoint
                    path('', PurchaseOrderDetail.as_view(), name='api-po-detail'),
                ]),
            ),
            # Purchase order status code information
            path(
                'status/',
                StatusView.as_view(),
                {StatusView.MODEL_REF: PurchaseOrderStatus},
                name='api-po-status-codes',
            ),
            # Purchase order list
            path('', PurchaseOrderList.as_view(), name='api-po-list'),
            path("build-impact/", purchase_order_build_impact, name="po-build-impact"),
            path("assign-shortfalls/", assign_shortfalls_to_po, name="assign-shortfalls"),
        ]),
    ),
    # API endpoints for purchase order line items
    path(
        'po-line/',
        include([
            path(
                '<int:pk>/',
                include([
                    path(
                        'metadata/',
                        MetadataView.as_view(model=models.PurchaseOrderLineItem),
                        name='api-po-line-metadata',
                    ),
                    path(
                        '',
                        PurchaseOrderLineItemDetail.as_view(),
                        name='api-po-line-detail',
                    ),
                ]),
            ),
            path('', PurchaseOrderLineItemList.as_view(), name='api-po-line-list'),
        ]),
    ),
    # API endpoints for purchase order extra line
    path(
        'po-extra-line/',
        include([
            path(
                '<int:pk>/',
                include([
                    path(
                        'metadata/',
                        MetadataView.as_view(model=models.PurchaseOrderExtraLine),
                        name='api-po-extra-line-metadata',
                    ),
                    path(
                        '',
                        PurchaseOrderExtraLineDetail.as_view(),
                        name='api-po-extra-line-detail',
                    ),
                ]),
            ),
            path(
                '', PurchaseOrderExtraLineList.as_view(), name='api-po-extra-line-list'
            ),
        ]),
    ), 
    # API endpoints for sales ordesr
    path(
        'so/',
        include([ 
            path('batch-shipping-label/', SalesOrderBatchShippingLabelStart.as_view()),
             # ✅ Generate DTDC AWB and store in SalesOrderShipment
            path('generate-dtdc/', SalesOrderGenerateDTDC.as_view(), name='api-so-generate-dtdc'),
            path('batch-shipping-label-progress/<uuid:task_id>/', SalesOrderBatchShippingLabelProgress.as_view()),
            path('batch-shipping-label-download/<uuid:task_id>/', SalesOrderBatchShippingLabelDownload.as_view()),
            path('batch-invoice-download/<uuid:task_id>/', SalesOrderBatchInvoiceDownload.as_view()),
            path('generate-invoice/', SalesOrderGenerateInvoice.as_view(), name='api-so-generate-invoice'),
            path('scan-ship/<str:barcode>/', scan_and_ship_order, name='api-so-scan-ship'),
            path('scan-history/', scan_history_list, name='api-so-scan-history'),
            # API endpoints for sales order shipments
            path(
                'shipment/',
                include([
                    path(
                        '<int:pk>/',
                        include([
                            path(
                                'ship/',
                                SalesOrderShipmentComplete.as_view(),
                                name='api-so-shipment-ship',
                            ),
                            path(
                                'metadata/',
                                MetadataView.as_view(model=models.SalesOrderShipment),
                                name='api-so-shipment-metadata',
                            ),
                            path(
                                '',
                                SalesOrderShipmentDetail.as_view(),
                                name='api-so-shipment-detail',
                            ),
                        ]),
                    ),
                    path(
                        '',
                        SalesOrderShipmentList.as_view(),
                        name='api-so-shipment-list',
                    ),
                ]),
            ),
            # Sales order detail view
            path(
                '<int:pk>/',
                include([
                    path(
                        'shipping-label/',                     # 👈 add this block
                        SalesOrderShippingLabel.as_view(),
                        name='api-sales-order-shipping-label', #      exact reverse() name
                    ),
                    path(
                        'allocate/',
                        SalesOrderAllocate.as_view(),
                        name='api-so-allocate',
                    ),
                    path(
                        'allocate-serials/',
                        SalesOrderAllocateSerials.as_view(),
                        name='api-so-allocate-serials',
                    ),
                    path('hold/', SalesOrderHold.as_view(), name='api-so-hold'),
                    path('cancel/', SalesOrderCancel.as_view(), name='api-so-cancel'),
                    path('issue/', SalesOrderIssue.as_view(), name='api-so-issue'),
                    path(
                        'complete/',
                        SalesOrderComplete.as_view(),
                        name='api-so-complete',
                    ),
                    path(
                        'metadata/',
                        MetadataView.as_view(model=models.SalesOrder),
                        name='api-so-metadata',
                    ),
                    # SalesOrder detail endpoint
                    path('', SalesOrderDetail.as_view(), name='api-so-detail'),
                ]),
            ),
            # Sales order status code information
            path(
                'status/',
                StatusView.as_view(),
                {StatusView.MODEL_REF: SalesOrderStatus},
                name='api-so-status-codes',
            ),
            # Sales order list view
            path('', SalesOrderList.as_view(), name='api-so-list'),
        ]),
    ),
    path('shipment-email/', send_shipment_email, name='api-order-shipment-email'),

      path(
        'courier-company/',
        include([
            path('', CourierCompanyViewSet.as_view({'get': 'list', 'post': 'create'}), name='api-courier-company-list'),
            path('<int:pk>/', CourierCompanyViewSet.as_view({'get': 'retrieve', 'put': 'update', 'delete': 'destroy'}), name='api-courier-company-detail'),
        ]),
    ),
    # API endpoints for sales order line items
    path(
        'so-line/',
        include([
            path(
                '<int:pk>/',
                include([
                    path(
                        'metadata/',
                        MetadataView.as_view(model=models.SalesOrderLineItem),
                        name='api-so-line-metadata',
                    ),
                    path(
                        '',
                        SalesOrderLineItemDetail.as_view(),
                        name='api-so-line-detail',
                    ),
                ]),
            ),
            path('', SalesOrderLineItemList.as_view(), name='api-so-line-list'),
        ]),
    ),
    # API endpoints for sales order extra line
    path(
        'so-extra-line/',
        include([
            path(
                '<int:pk>/',
                include([
                    path(
                        'metadata/',
                        MetadataView.as_view(model=models.SalesOrderExtraLine),
                        name='api-so-extra-line-metadata',
                    ),
                    path(
                        '',
                        SalesOrderExtraLineDetail.as_view(),
                        name='api-so-extra-line-detail',
                    ),
                ]),
            ),
            path('', SalesOrderExtraLineList.as_view(), name='api-so-extra-line-list'),
        ]),
    ),
    # API endpoints for sales order allocations
    path(
        'so-allocation/',
        include([
            path(
                '<int:pk>/',
                SalesOrderAllocationDetail.as_view(),
                name='api-so-allocation-detail',
            ),
            path('', SalesOrderAllocationList.as_view(), name='api-so-allocation-list'),
        ]),
    ),
    # API endpoints for return orders
    path(
        'ro/',
        include([
            # Return Order detail endpoints
            path(
                '<int:pk>/',
                include([
                    path(
                        'cancel/',
                        ReturnOrderCancel.as_view(),
                        name='api-return-order-cancel',
                    ),
                    path('hold/', ReturnOrderHold.as_view(), name='api-ro-hold'),
                    path(
                        'complete/',
                        ReturnOrderComplete.as_view(),
                        name='api-return-order-complete',
                    ),
                    path(
                        'issue/',
                        ReturnOrderIssue.as_view(),
                        name='api-return-order-issue',
                    ),
                    path(
                        'receive/',
                        ReturnOrderReceive.as_view(),
                        name='api-return-order-receive',
                    ),
                    path(
                        'metadata/',
                        MetadataView.as_view(model=models.ReturnOrder),
                        name='api-return-order-metadata',
                    ),
                    path(
                        '', ReturnOrderDetail.as_view(), name='api-return-order-detail'
                    ),
                ]),
            ),
            # Return order status code information
            path(
                'status/',
                StatusView.as_view(),
                {StatusView.MODEL_REF: ReturnOrderStatus},
                name='api-return-order-status-codes',
            ),
            # Return Order list
            path('', ReturnOrderList.as_view(), name='api-return-order-list'),
        ]),
    ),
    # API endpoints for return order lines
    path(
        'ro-line/',
        include([
            path(
                '<int:pk>/',
                include([
                    path(
                        'metadata/',
                        MetadataView.as_view(model=models.ReturnOrderLineItem),
                        name='api-return-order-line-metadata',
                    ),
                    path(
                        '',
                        ReturnOrderLineItemDetail.as_view(),
                        name='api-return-order-line-detail',
                    ),
                ]),
            ),
            # Return order line item status code information
            path(
                'status/',
                StatusView.as_view(),
                {StatusView.MODEL_REF: ReturnOrderLineStatus},
                name='api-return-order-line-status-codes',
            ),
            path(
                '', ReturnOrderLineItemList.as_view(), name='api-return-order-line-list'
            ),
        ]),
    ),
    # API endpoints for return order extra line
    path(
        'ro-extra-line/',
        include([
            path(
                '<int:pk>/',
                include([
                    path(
                        'metadata/',
                        MetadataView.as_view(model=models.ReturnOrderExtraLine),
                        name='api-return-order-extra-line-metadata',
                    ),
                    path(
                        '',
                        ReturnOrderExtraLineDetail.as_view(),
                        name='api-return-order-extra-line-detail',
                    ),
                ]),
            ),
            path(
                '',
                ReturnOrderExtraLineList.as_view(),
                name='api-return-order-extra-line-list',
            ),
        ]),
    ),
    # API endpoint for subscribing to ICS calendar of purchase/sales/return orders
    re_path(
        r'^calendar/(?P<ordertype>purchase-order|sales-order|return-order)/calendar.ics',
        OrderCalendarExport(),
        name='api-po-so-calendar',
    ),
]

