#!/usr/bin/env python3
"""
extract_multiple.py

Usage:
    python extract_multiple.py                    # Defaults: data.json ➜ output.json
    python extract_multiple.py input.json output.json
"""

import json
import sys
from pathlib import Path


def load_fixture(path: Path):
    """Return list of fixture objects. Handles both:
       • one big JSON array   • one-object-per-line dumps"""
    raw = path.read_text(encoding="utf-8")
    try:  # normal array?
        return json.loads(raw)
    except json.JSONDecodeError:
        return [json.loads(line) for line in raw.splitlines() if line.strip()]


def save_to_file(data, out_path: Path):
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✅ Wrote {len(data)} records ➜ {out_path.resolve()}")


def filter_records(records, models_to_keep):
    """Filter records by given models."""
    return [r for r in records if r.get("model") in models_to_keep]


def sanitize_part_data(parts):
    """Sanitize part records by removing unwanted fields."""
    for part in parts:
        if part.get("model") == "part.part":
            part.get("fields", {}).pop("default_supplier", None)
    return parts


def remove_icon_from_part_category(categories):
    """Remove the 'icon' field from part category records."""
    for category in categories:
        if category.get("model") == "part.partcategory":
            category.get("fields", {}).pop("icon", None)
    return categories

def clean_salesorders(records):
    """Clean sales order records by removing gst_number if it is null."""
    cleaned_salesorders = []
    for record in records:
        if record.get("model") == "order.salesorder":
            fields = record.get("fields", {})
            # Remove gst_number if it's None
            if fields.get("gst_number") is None:
                fields.pop("gst_number", None)

            # Optionally, set a default for gst_number (uncomment to use)
            # if not fields.get("gst_number"):
            #     fields["gst_number"] = "NA"
            
            cleaned_salesorders.append(record)
    return cleaned_salesorders


def main():
    input_file = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data.json")
    output_file = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("output.json")
    
    if not input_file.exists():
        sys.exit(f"❌ Input file not found: {input_file}")
    
    records = load_fixture(input_file)

    # List to accumulate all the filtered records in a single array
    all_filtered_records = []

    # Define the models that we want to include in the output
    filters = [
        "auth.user",
        "auth.group",
        "users.owner",
        "users.ruleset",
        "company.company",
        "company.address",
        "company.contact",
        "stock.stocklocation",
        "part.partcategory",
        "part.part",
        "company.manufacturerpart",
        "company.supplierpart",
        "part.bomitem",
        "build.build",
        "build.buildline",
        "order.salesorder",
        "order.salesorderlineitem",
        "stock.stocklocation",
        "stock.stockitem",
        "stock.stockitemtracking",
    "order.couriercompany",
   "order.salesordershipment",
        "order.salesorderallocation",
    
        "order.returnorder",
        "order.returnorderlineitem",
       
        "order.purchaseorder",
        "order.purchaseorderlineitem",
        "part.partpricing",
"plugin.notificationusersetting",
"common.inventreeusersetting",
"common.inventreesetting",
"part.componentverificationchecklist",
"common.newsfeedentry",
"part.bomitemsubstitute",
"account.emailaddress",
"part.partstar",
"part.partrelated"

#  "common.inventreeusersetting",
#     "company.supplierpart",
#     "order.purchaseorderlineitem",
#     "part.bomitem",
#     "order.couriercompany",
#     "company.manufacturerpart",
#     "order.returnorder",
#     "stock.stocklocation",
#     "company.address",
#     "exchange.exchangebackend",
#     "order.salesordershipment",
#     "usersessions.usersession",
#     "company.company",
#     "django_q.ormq",
#     "account.emailaddress",
#     "order.salesorder",
#     "common.inventreesetting",
#     "auth.group",
#     "common.newsfeedentry",
#     "stock.stockitemtracking",
#     "part.partrelated",
#     "users.ruleset",
#     "plugin.notificationusersetting",
#     "part.componentverificationchecklist",
   
#     "users.owner",
#     "part.partcategory",
#     "part.bomitemsubstitute",
  
#     "contenttypes.contenttype",
#     "order.returnorderlineitem",
#     "part.part",
#     "build.build",
  
#     "build.buildline",
#     "stock.stockitem",
#     "order.salesorderlineitem",
#     "part.partstar",
#     "company.contact",
#     "order.salesorderallocation",
#     "exchange.rate",
#     "auth.permission",
#     "auth.user",
#     "order.purchaseorder",
#     "sessions.session",
#     "part.partpricing"


       

##-----------------------------------------------
     # "part.partattachment",
        # "part.parttesttemplate",

    ]

    # Extract and accumulate records for each model
    for model in filters:
        filtered = filter_records(records, {model})
        
        # Special handling for part categories and parts
        if model == "part.partcategory" and filtered:
            filtered = remove_icon_from_part_category(filtered)
            all_filtered_records.extend(filtered)  # Add directly to the list
        elif model == "part.part" and filtered:
            filtered = sanitize_part_data(filtered)
            all_filtered_records.extend(filtered)  # Add directly to the list
        elif model == "order.salesorder" and filtered:
            filtered_salesorders = clean_salesorders(filtered)
            all_filtered_records.extend(filtered_salesorders)  # Add cleaned sales orders    
        elif filtered:
            all_filtered_records.extend(filtered)  # Add directly to the list
        else:
            print(f"⚠️ No records found for model: {model}")

    # Save all the filtered records in a single output file
    save_to_file(all_filtered_records, output_file)


if __name__ == "__main__":
    main()
