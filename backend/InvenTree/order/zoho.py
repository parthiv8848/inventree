import requests
from django.conf import settings
import json
import time
import phonenumbers


# This is where we would store the expiration time for the token
# For now, let's assume it will be stored in memory (you can store this in a database or a file for persistent storage)
token_cache = {
    "access_token": None,
    "expires_at": 0  # Timestamp when the token expires
}

def get_zoho_access_token():
    # Check if the token is still valid
    current_time = int(time.time())  # Get the current time in seconds
    if token_cache["access_token"] and token_cache["expires_at"] > current_time:
        # Token is still valid, no need to refresh
        # print("[DEBUG] Using cached Zoho access token.")
        return token_cache["access_token"]

    # If the token is expired or doesn't exist, refresh it
    client_id = settings.ZOHO_BOOKS["client_id"]
    client_secret = settings.ZOHO_BOOKS["client_secret"]
    refresh_token = settings.ZOHO_BOOKS["refresh_token"]
    zoho_domain = settings.ZOHO_BOOKS.get("domain", "https://accounts.zoho.in")

    token_url = f"{zoho_domain}/oauth/v2/token"

    payload = {
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token"
    }

    response = requests.post(token_url, data=payload)
    response_data = response.json()
    # print(f"[DEBUG] Zoho token response: {response_data}")

    if response.status_code != 200:
        raise Exception(f"Failed to refresh Zoho token: {response_data}")

    # Cache the new token and expiration time
    access_token = response_data["access_token"]
    expires_in = response_data.get("expires_in", 3600)  # Default to 3600 seconds if not specified

    token_cache["access_token"] = access_token
    token_cache["expires_at"] = current_time + expires_in  # Set expiration time

    return access_token

# token = get_zoho_access_token()
# print(f"[DEBUG] Zoho access token: {token[:10]}...")  # Print only the first 10 characters for security
# token = get_zoho_access_token()
# print(f"[DEBUG] Zoho access token: {token[:10]}...")  # Print only the first 10 characters for security


def get_zoho_customers():
    url = "https://www.zohoapis.in/books/v3/customers"
    params = {
        "organization_id": settings.ZOHO_BOOKS["organization_id"]
    }
    headers = {
        "Authorization": f"Zoho-oauthtoken {get_zoho_access_token()}",
        "Content-Type": "application/json"
    }

    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    
    data = response.json()
    # print(f"[DEBUG] Zoho API Response: {data}")
    customers = data.get("contacts", [])

    return customers


def get_zoho_customer_by_email(email):
    """Search Zoho customer by email."""
    token = get_zoho_access_token()
    url = "https://www.zohoapis.in/books/v3/contacts"
    headers = {
        "Authorization": f"Zoho-oauthtoken {token}",
        "Content-Type": "application/json"
    }
    params = {
        "organization_id": settings.ZOHO_BOOKS["organization_id"],
        "email": email
    }

    response = requests.get(url, headers=headers, params=params)
    data = response.json()
    contacts = data.get("contacts", [])
    return contacts[0] if contacts else None


def get_zoho_customer_by_name(name):
    """
    Search Zoho customer directly from Zoho Books API using contact_name.
    
    Args:
        name (str): The name to search for (contact_name)
    
    Returns:
        dict: Zoho contact if found, else None
    """
    if not name:
        return None

    token = get_zoho_access_token()
    url = "https://www.zohoapis.in/books/v3/contacts"
    headers = {
        "Authorization": f"Zoho-oauthtoken {token}",
        "Content-Type": "application/json"
    }

    params = {
        "organization_id": settings.ZOHO_BOOKS["organization_id"],
        "contact_name": name.strip()
    }

    response = requests.get(url, headers=headers, params=params)
    data = response.json()

    # Debug logging (optional)
    print(f"[DEBUG] Zoho name search response: {data}")

    # Return the first matching contact if any
    contacts = data.get("contacts", [])
    if contacts:
        return contacts[0]

    return None

def get_zoho_customer_by_phone(phone):
    """Search Zoho customer strictly by phone number."""
    if not phone:
        return None

    token = get_zoho_access_token()
    url = "https://www.zohoapis.in/books/v3/contacts"
    headers = {"Authorization": f"Zoho-oauthtoken {token}", "Content-Type": "application/json"}

    # Only search by phone, ignore mobile
    params = {
        "organization_id": settings.ZOHO_BOOKS["organization_id"],
        "phone": phone
    }

    response = requests.get(url, headers=headers, params=params)
    data = response.json()
    contacts = data.get("contacts", [])

    # Return the first contact if any, otherwise None
    if contacts:
        return contacts[0]

    return None 

import re

def format_phone(phone):
    # Remove all non-digit characters except leading '+'
    phone = re.sub(r'[^\d+]', '', phone)

    if phone.startswith('+') and len(phone) > 5:
        country_code = phone[1:3]  # Adjust depending on country codes
        number = phone[3:]
        # Break into chunks like 3-3-4
        formatted_number = f"+{country_code}-{number[:3]}{number[3:6]}{number[6:]}"
        return formatted_number

    return phone  # Return as is if formatting fails


def normalize_phone_e164(phone, default_region='IN'):
    """
    Normalize a phone number to E.164 format (e.g., +911234567890).
    If parsing fails, fallback to removing non-digit characters.
    """
    try:
        parsed = phonenumbers.parse(phone, default_region)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        pass
    # Fallback: remove all non-digits and assume it's local
    return re.sub(r'\D', '', phone or '')



def create_zoho_customer(customer):
    url = "https://www.zohoapis.in/books/v3/contacts"
    token = get_zoho_access_token()
    # print(f"[DEBUG] Token used in create_zoho_customer: {token[:10]}...")

    # print customer
    print(f"[DEBUG] Creating Zoho customer for: {customer}")
    for key, value in customer.__dict__.items():
        print(f"[DEBUG] {key}: {value}")
        pass

    # debug address
    print(f"[DEBUG] Customer address: {customer.address}")

    headers = {
        "Authorization": f"Zoho-oauthtoken {token}",
        "Content-Type": "application/json"
    }

    # Define main contact email and name
    contact_name = customer.name or customer.individual_name or customer.contact or "Unnamed Contact" 
    primary_email = customer.email or ""
    
    # Example additional emails (you can get these from your model or metadata)
    extra_emails = getattr(customer, "metadata", {}).get("extra_emails", [])

    # Build contact persons
    contact_persons = [
        {
            "first_name": contact_name.split()[0],
            "last_name": contact_name.split()[1] if len(contact_name.split()) > 1 else "",
            "email": primary_email,
            "phone": customer.phone,
            # "phone": format_phone(customer.phone)

        }
    ]


    for email in enumerate(extra_emails):
        contact_persons.append({
            "email": email
        })
    # Log all primary address fields
    addr = getattr(customer, 'primary_address', None)
    if addr:
        print("[DEBUG] Customer primary address fields:")
        print(f"  Line 1:     {getattr(addr, 'line1', None)}")
        print(f"  Line 2:     {getattr(addr, 'line2', None)}")
        print(f"  City:       {getattr(addr, 'postal_city', None)}")
        print(f"  State:      {getattr(addr, 'province', None)}")
        print(f"  Postcode:   {getattr(addr, 'postal_code', None)}")
        print(f"  Country:    {getattr(addr, 'country', None)}")
        
        print(f"  Company:    {customer.name}")
        billing_address = {
            
            "attention": customer.contact or customer.individual_name or customer.name or "Unnamed Contact",
            "address": getattr(addr, 'line1', '') or '',
            "street2": getattr(addr, 'line2', '') or '',
            "city": getattr(addr, 'postal_city', '') or '',
            "state": getattr(addr, 'province', '') or '',
            "zip": getattr(addr, 'postal_code', '') or '',
            "country": getattr(addr, 'country', '') or '',
            "phone": customer.phone or ''
        }
    else:
        print("[DEBUG] No primary address set for customer.")
        billing_address = {
            "address": customer.address or '',
            "phone": customer.phone or ''
        }

    payload = {
        "company_name": customer.name or "Unnamed Company",
        "contact_name": contact_name,
        "email": primary_email,
        "contact_persons": contact_persons,
        "billing_address": billing_address,
        "shipping_address": billing_address,
    }

    # If the customer is B2B and has a valid GST number
    
    if customer.gst_number and customer.gst_number.lower() != "nil":
            payload["gst_treatment"] = "business_gst"
            payload["gst_no"] = customer.gst_number
            print(f"[DEBUG] Added GST Info: {customer.gst_number}")
    else:
            print("[DEBUG] B2B customer does not have a valid GST number")

    print(f"[DEBUG] Zoho create customer payload: {json.dumps(payload, indent=2)}")

    params = {"organization_id": settings.ZOHO_BOOKS["organization_id"]}

    try:
        res = requests.post(url, headers=headers, params=params, json=payload)
        print("[DEBUG] Zoho create customer response:", res.status_code, res.text)
        res.raise_for_status()

        response_json = res.json()
        message = response_json.get("message", "Customer created.")
        contact_id = response_json.get("contact", {}).get("contact_id")
        return {
            "message": message,
            "contact_id": contact_id
        }

    except requests.exceptions.HTTPError as e:
        try:
            error_response = res.json()
            error_message = error_response.get("message", "Unknown error occurred.")
        except Exception:
            error_message = str(e)
        
        print(f"[ERROR] Zoho API Error: {error_message}")
        return error_message

def update_zoho_customer(contact_id, customer):
    """
    Update an existing Zoho customer with the latest details.
    """
    token = get_zoho_access_token()
    url = f"https://www.zohoapis.in/books/v3/contacts/{contact_id}"
    headers = {
        "Authorization": f"Zoho-oauthtoken {token}",
        "Content-Type": "application/json"
    }

    # Prepare the updated data (similar to create_zoho_customer)
    contact_name = customer.name or customer.individual_name or customer.contact or "Unnamed Contact"
    primary_email = customer.email or ""

    addr = getattr(customer, 'primary_address', None)
    if addr:
        billing_address = {
            "attention": contact_name,
            "address": getattr(addr, 'line1', '') or '',
            "street2": getattr(addr, 'line2', '') or '',
            "city": getattr(addr, 'postal_city', '') or '',
            "state": getattr(addr, 'province', '') or '',
            "zip": getattr(addr, 'postal_code', '') or '',
            "country": getattr(addr, 'country', '') or '',
            "phone": customer.phone or ''
        }
    else:
        billing_address = {
            "address": customer.address or '',
            "phone": customer.phone or ''
        }

    payload = {
        "company_name": customer.name or "Unnamed Company",
        "contact_name": contact_name,
        "email": primary_email,
        "phone": customer.phone or "",
        "billing_address": billing_address,
        "shipping_address": billing_address,
    }

    # Add GST info if available
    if customer.gst_number and customer.gst_number.lower() != "nil":
        payload["gst_treatment"] = "business_gst"
        payload["gst_no"] = customer.gst_number

    params = {"organization_id": settings.ZOHO_BOOKS["organization_id"]}

    print(f"[DEBUG] Updating Zoho customer {contact_id} with payload: {json.dumps(payload, indent=2)}")

    try:
        res = requests.put(url, headers=headers, params=params, json=payload)
        print("[DEBUG] Zoho update customer response:", json.dumps(res.json(), indent=2))
        res.raise_for_status()

        data = res.json()
        message = data.get("message", "Customer updated.")
        return {"success": True, "message": message}

    except requests.exceptions.HTTPError as e:
        try:
            error_message = res.json().get("message", str(e))
        except Exception:
            error_message = str(e)
        print(f"[ERROR] Failed to update Zoho customer: {error_message}")
        return {"success": False, "message": error_message}


def get_zoho_items():
    url = "https://www.zohoapis.in/books/v3/items"
    token = get_zoho_access_token()
    headers = {
        "Authorization": f"Zoho-oauthtoken {token}",
        "Content-Type": "application/json"
    }
    params = {"organization_id": settings.ZOHO_BOOKS["organization_id"]}
    res = requests.get(url, headers=headers, params=params)
    res.raise_for_status()
    return res.json().get("items", [])

def create_zoho_item(line):
    part = line.part
    
    rate = 0.0

    if line.sale_price:
        rate = float(line.sale_price.amount)
    else:
        print(f"[WARNING] No sale_price found for part {part.full_name}, setting rate=0.0")

    category = getattr(part, 'category', None)
    if category:
        print(f"[DEBUG] part_category: {category.name}")
    else:
        print("[DEBUG] part_category: None")

    url = "https://www.zohoapis.in/books/v3/items"
    token = get_zoho_access_token()
    headers = {
        "Authorization": f"Zoho-oauthtoken {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "name": category.name if category else part.full_name,
        "rate": rate,
        "description": part.description or part.full_name,
        "unit": part.units or "nos",
    }

    print(f"[DEBUG] Zoho item payload: {json.dumps(payload, indent=2)}")

    params = {"organization_id": settings.ZOHO_BOOKS["organization_id"]}
    res = requests.post(url, headers=headers, params=params, json=payload)
    res.raise_for_status()
    return res.json()["item"]["item_id"]

# ==================== INVOICE FUNCTIONS ====================

def get_zoho_invoices(page=1, per_page=20, status=None, customer_id=None, date_from=None, date_to=None):
    """
    Fetch invoices from Zoho Books with optional filters
    
    Args:
        page (int): Page number (default: 1)
        per_page (int): Number of invoices per page (max 200, default: 20)
        status (str): Invoice status - 'draft', 'sent', 'overdue', 'paid', etc.
        customer_id (str): Filter by specific customer
        date_from (str): Start date in YYYY-MM-DD format
        date_to (str): End date in YYYY-MM-DD format
    
    Returns:
        dict: Response containing invoices list and pagination info
    """
    url = "https://www.zohoapis.in/books/v3/invoices"
    token = get_zoho_access_token()
    headers = {
        "Authorization": f"Zoho-oauthtoken {token}",
        "Content-Type": "application/json"
    }
    
    params = {
        "organization_id": settings.ZOHO_BOOKS["organization_id"],
        "page": page,
        "per_page": min(per_page, 200)  # Zoho max is 200
    }
    
    # Add optional filters
    if status:
        params["status"] = status
    if customer_id:
        params["customer_id"] = customer_id
    if date_from:
        params["date_start"] = date_from
    if date_to:
        params["date_end"] = date_to

    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        
        data = response.json()
        print(f"[DEBUG] Fetched {len(data.get('invoices', []))} invoices from Zoho")
        return data
        
    except requests.exceptions.HTTPError as e:
        print(f"[ERROR] Failed to fetch Zoho invoices: {e}")
        return {"invoices": [], "page_context": {}}


def get_zoho_invoice_details(invoice_id):
    """
    Get detailed information for a specific invoice
    
    Args:
        invoice_id (str): The Zoho invoice ID
        
    Returns:
        dict: Detailed invoice information
    """
    url = f"https://www.zohoapis.in/books/v3/invoices/{invoice_id}"
    token = get_zoho_access_token()
    headers = {
        "Authorization": f"Zoho-oauthtoken {token}",
        "Content-Type": "application/json"
    }
    
    params = {"organization_id": settings.ZOHO_BOOKS["organization_id"]}
    
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        
        data = response.json()
        invoice = data.get("invoice", {})
        print(f"[DEBUG] Fetched invoice details for ID: {invoice_id}")
        return invoice
        
    except requests.exceptions.HTTPError as e:
        print(f"[ERROR] Failed to fetch invoice details for ID {invoice_id}: {e}")
        return {}


def create_zoho_invoice(customer_id, line_items, invoice_data=None, shipping_charge=100.0):
    """
    Create a new invoice in Zoho Books
    
    Args:
        customer_id (str): Zoho customer ID
        line_items (list): List of line items for the invoice
        invoice_data (dict): Additional invoice data (optional)
    
    Example line_items format:
    [
        {
            "item_id": "item_id_from_zoho",
            "name": "Product Name",
            "rate": 100.0,
            "quantity": 2,
            "description": "Product description"
        }
    ]
    
    Returns:
        dict: Created invoice response
    """
    url = "https://www.zohoapis.in/books/v3/invoices"
    token = get_zoho_access_token()
    headers = {
        "Authorization": f"Zoho-oauthtoken {token}",
        "Content-Type": "application/json"
    }
    
    # Default invoice data
    default_data = {
        "customer_id": customer_id,
        "line_items": line_items,
        "shipping_charge": shipping_charge
    }

    # Merge with additional data if provided
    if invoice_data:
        default_data.update(invoice_data)
    
    params = {"organization_id": settings.ZOHO_BOOKS["organization_id"]}
    
    print(f"[DEBUG] Creating Zoho invoice with payload: {json.dumps(default_data, indent=2)}")
    
    try:
        response = requests.post(url, headers=headers, params=params, json=default_data)
        response.raise_for_status()
        
        response_data = response.json()
        invoice = response_data.get("invoice", {})
        invoice_id = invoice.get("invoice_id")
        
        print(f"[DEBUG] Successfully created Zoho invoice with ID: {invoice_id}")
        return {
            "success": True,
            "invoice_id": invoice_id,
            "invoice": invoice,
            "message": response_data.get("message", "Invoice created successfully")
        }
        
    except requests.exceptions.HTTPError as e:
        try:
            error_response = response.json()
            error_message = error_response.get("message", "Unknown error occurred.")
        except Exception:
            error_message = str(e)
        
        print(f"[ERROR] Failed to create Zoho invoice: {error_message}")
        return {
            "success": False,
            "error": error_message
        }


def update_zoho_invoice(invoice_id, customer_id, line_items, shipping_charge=None, invoice_data=None, reason=None):
    """
    Update an existing Zoho Invoice.

    Args:
        invoice_id (str): The Zoho Invoice ID to update
        customer_id (str): Zoho Customer ID
        line_items (list): List of line items to update
        shipping_charge (float or None): Optional shipping charge. If None, existing charge remains unchanged.
        invoice_data (dict): Optional extra fields for invoice update
        reason (str or None): Optional reason for updating a sent invoice (required by Zoho)
    """
    url = f"https://www.zohoapis.in/books/v3/invoices/{invoice_id}"
    token = get_zoho_access_token()
    headers = {
        "Authorization": f"Zoho-oauthtoken {token}",
        "Content-Type": "application/json"
    }

    payload = {
        "customer_id": customer_id,
        "line_items": line_items
    }

    # ✅ Only include shipping charge if explicitly passed
    if shipping_charge is not None:
        payload["shipping_charge"] = shipping_charge

    # ✅ Add a default reason if required
    if reason:
        payload["reason"] = reason
    else:
        payload["reason"] = "Invoice item or shipping charge updated automatically via system"

    # ✅ Merge extra data if provided
    if invoice_data:
        payload.update(invoice_data)

    params = {"organization_id": settings.ZOHO_BOOKS["organization_id"]}

    print(f"[DEBUG] Updating Zoho invoice {invoice_id} with payload: {json.dumps(payload, indent=2)}")

    try:
        response = requests.put(url, headers=headers, params=params, json=payload)
        response.raise_for_status()

        response_data = response.json()
        invoice = response_data.get("invoice", {})

        print(f"[DEBUG] Successfully updated Zoho invoice ID: {invoice_id}")
        return {
            "success": True,
            "invoice_id": invoice_id,
            "invoice": invoice,
            "message": response_data.get("message", "Invoice updated successfully")
        }

    except requests.exceptions.HTTPError as e:
        try:
            error_response = response.json()
            error_message = error_response.get("message", "Unknown error occurred.")
        except Exception:
            error_message = str(e)

        print(f"[ERROR] Failed to update Zoho invoice: {error_message}")
        return {
            "success": False,
            "error": error_message
        }


def send_zoho_invoice(invoice_id, send_customer_statement=False, send_attachment=True):
    """
    Send an invoice via email through Zoho Books
    
    Args:
        invoice_id (str): The Zoho invoice ID to send
        send_customer_statement (bool): Include customer statement
        send_attachment (bool): Include PDF attachment
        
    Returns:
        dict: Send response
    """
    url = f"https://www.zohoapis.in/books/v3/invoices/{invoice_id}/status/sent"
    token = get_zoho_access_token()
    headers = {
        "Authorization": f"Zoho-oauthtoken {token}",
        "Content-Type": "application/json"
    }
    
    params = {
        "organization_id": settings.ZOHO_BOOKS["organization_id"],
        "send_customer_statement": send_customer_statement,
        "send_attachment": send_attachment
    }
    
    try:
        response = requests.post(url, headers=headers, params=params)
        response.raise_for_status()
        
        response_data = response.json()
        print(f"[DEBUG] Successfully sent Zoho invoice ID: {invoice_id}")
        return {
            "success": True,
            "message": response_data.get("message", "Invoice sent successfully")
        }
        
    except requests.exceptions.HTTPError as e:
        try:
            error_response = response.json()
            error_message = error_response.get("message", "Unknown error occurred.")
        except Exception:
            error_message = str(e)
        
        print(f"[ERROR] Failed to send Zoho invoice {invoice_id}: {error_message}")
        return {
            "success": False,
            "error": error_message
        }


def get_zoho_invoice_pdf(invoice_id):
    """
    Download invoice PDF from Zoho Books
    
    Args:
        invoice_id (str): The Zoho invoice ID
        
    Returns:
        bytes: PDF content or None if failed
    """
    url = f"https://www.zohoapis.in/books/v3/invoices/{invoice_id}"
    token = get_zoho_access_token()
    headers = {
        "Authorization": f"Zoho-oauthtoken {token}",
        "Accept": "application/pdf"
    }
    
    params = {"organization_id": settings.ZOHO_BOOKS["organization_id"]}
    
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        
        print(f"[DEBUG] Successfully downloaded PDF for invoice ID: {invoice_id}")
        return response.content
        
    except requests.exceptions.HTTPError as e:
        print(f"[ERROR] Failed to download PDF for invoice {invoice_id}: {e}")
        return None


def delete_zoho_invoice(invoice_id):
    """
    Delete an invoice from Zoho Books
    
    Args:
        invoice_id (str): The Zoho invoice ID to delete
        
    Returns:
        dict: Delete response
    """
    url = f"https://www.zohoapis.in/books/v3/invoices/{invoice_id}"
    token = get_zoho_access_token()
    headers = {
        "Authorization": f"Zoho-oauthtoken {token}",
        "Content-Type": "application/json"
    }
    
    params = {"organization_id": settings.ZOHO_BOOKS["organization_id"]}
    
    try:
        response = requests.delete(url, headers=headers, params=params)
        response.raise_for_status()
        
        response_data = response.json()
        print(f"[DEBUG] Successfully deleted Zoho invoice ID: {invoice_id}")
        return {
            "success": True,
            "message": response_data.get("message", "Invoice deleted successfully")
        }
        
    except requests.exceptions.HTTPError as e:
        try:
            error_response = response.json()
            error_message = error_response.get("message", "Unknown error occurred.")
        except Exception:
            error_message = str(e)
        
        print(f"[ERROR] Failed to delete Zoho invoice {invoice_id}: {error_message}")
        return {
            "success": False,
            "error": error_message
        }


# ==================== HELPER FUNCTIONS ====================

def get_customer_invoices(customer_id, status=None):
    """
    Get all invoices for a specific customer
    
    Args:
        customer_id (str): Zoho customer ID
        status (str): Optional status filter
        
    Returns:
        list: List of customer invoices
    """
    invoices_data = get_zoho_invoices(customer_id=customer_id, status=status, per_page=200)
    return invoices_data.get("invoices", [])


def search_invoices_by_number(invoice_number):
    """
    Search for invoices by invoice number
    
    Args:
        invoice_number (str): Invoice number to search for
        
    Returns:
        list: List of matching invoices
    """
    url = "https://www.zohoapis.in/books/v3/invoices"
    token = get_zoho_access_token()
    headers = {
        "Authorization": f"Zoho-oauthtoken {token}",
        "Content-Type": "application/json"
    }
    
    params = {
        "organization_id": settings.ZOHO_BOOKS["organization_id"],
        "invoice_number": invoice_number
    }
    
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        
        data = response.json()
        return data.get("invoices", [])
        
    except requests.exceptions.HTTPError as e:
        print(f"[ERROR] Failed to search invoices by number {invoice_number}: {e}")
        return []

from io import BytesIO
    
def download_zoho_invoice_pdf(invoice_number):
    """
    Download invoice PDF from Zoho Books by invoice number.
    Returns BytesIO object of PDF or None if not found.
    """
    access_token = get_zoho_access_token()
    organization_id = settings.ZOHO_BOOKS["organization_id"]
    base_url = "https://www.zohoapis.in/books/v3/invoices"

    # Step 1: Find the invoice ID using invoice number
    search_url = f"{base_url}?organization_id={organization_id}&invoice_number={invoice_number}"
    headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
    search_response = requests.get(search_url, headers=headers)
    data = search_response.json()

    if search_response.status_code != 200 or not data.get("invoices"):
        print(f"[ZOHO] Invoice not found for number: {invoice_number}")
        return None

    invoice_id = data["invoices"][0]["invoice_id"]

    # Step 2: Download the invoice PDF
    pdf_url = f"{base_url}/{invoice_id}?organization_id={organization_id}&accept=pdf"
    pdf_response = requests.get(pdf_url, headers=headers)

    if pdf_response.status_code != 200:
        print(f"[ZOHO] Failed to download invoice PDF for number: {invoice_number}")
        return None

    return BytesIO(pdf_response.content)

def get_zoho_invoice_by_number(invoice_number):
    """Fetch Zoho invoice by its invoice_number"""
    try:
        token = get_zoho_access_token()
        url = f"https://www.zohoapis.in/books/v3/invoices"
        params = {
            "organization_id": settings.ZOHO_BOOKS["organization_id"],
            "invoice_number": invoice_number
        }
        headers = {"Authorization": f"Zoho-oauthtoken {token}"}

        response = requests.get(url, headers=headers, params=params)
        data = response.json()

        if response.status_code == 200 and data.get("code") == 0:
            invoices = data.get("invoices", [])
            if invoices:
                return invoices[0]  # Return the first match
            else:
                print(f"[INFO] No Zoho invoice found for number: {invoice_number}")
                return None
        else:
            print(f"[ERROR] Failed to fetch Zoho invoice by number {invoice_number}: {data}")
            return None
    except Exception as e:
        print(f"[ERROR] Exception while fetching invoice by number {invoice_number}: {e}")
        return None
