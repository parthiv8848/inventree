"""Background tasks for the report app."""

import structlog
from opentelemetry import trace

from InvenTree.exceptions import log_error

tracer = trace.get_tracer(__name__)
logger = structlog.get_logger('inventree')


@tracer.start_as_current_span('print_reports')
def print_reports(template_id: int, item_ids: list[int], output_id: int, **kwargs):
    """Print multiple reports against the provided template.

    Arguments:
        template_id: The ID of the ReportTemplate to use
        item_ids: List of item IDs to generate the report against
        output_id: The ID of the DataOutput to use (if provided)

    This function is intended to be called by the background worker,
    and will continuously update the status of the DataOutput object.
    """
    from common.models import DataOutput
    from report.models import ReportTemplate

    try:
        template = ReportTemplate.objects.get(pk=template_id)
        output = DataOutput.objects.get(pk=output_id)
    except Exception:
        log_error('report.tasks.print_reports')
        return

    # Fetch the items to be included in the report
    model = template.get_model()
    items = model.objects.filter(pk__in=item_ids)

    template.print(items, output=output)


@tracer.start_as_current_span('print_labels')
def print_labels(
    template_id: int, 
    item_ids: list[int], 
    output_id: int, 
    plugin_slug: str, 
    options=None,  # ← ADD: Accept options as a named parameter
    **kwargs
):
    """Print multiple labels against the provided template.

    Arguments:
        template_id: The ID of the LabelTemplate to use
        item_ids: List of item IDs to generate the labels against
        output_id: The ID of the DataOutput to use (if provided)
        plugin_slug: The ID of the LabelPlugin to use (if provided)
        options: Dictionary of options for label printing

    This function is intended to be called by the background worker,
    and will continuously update the status of the DataOutput object.
    """
    from common.models import DataOutput
    from plugin.registry import registry
    from report.models import LabelTemplate

    # DEBUG: Add logging to see what we receive
    print("="*60)
    print("TASK: print_labels called with:")
    print(f"template_id: {template_id}")
    print(f"item_ids: {item_ids}")
    print(f"output_id: {output_id}")
    print(f"plugin_slug: {plugin_slug}")
    print(f"options parameter: {options}")
    print(f"kwargs: {kwargs}")
    print("="*60)

    try:
        template = LabelTemplate.objects.get(pk=template_id)
        output = DataOutput.objects.get(pk=output_id)
    except Exception:
        log_error('report.tasks.print_labels')
        return

    # Fetch the items to be included in the report
    model = template.get_model()
    items = model.objects.filter(pk__in=item_ids)

    plugin = registry.get_plugin(plugin_slug)

    if not plugin:
        logger.warning("Label printing plugin '%s' not found", plugin_slug)
        return

    # FIXED: Use the options parameter directly, with fallback to kwargs
    if options is None:
        options = kwargs.pop('options', {})
    
    # Ensure options is a dictionary
    if options is None:
        options = {}

    print(f"Final options being passed to template.print(): {options}")

    template.print(items, plugin, output=output, options=options)