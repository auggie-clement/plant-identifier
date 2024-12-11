
from datetime import datetime
import logging
import random
from flask import current_app, jsonify
import json
import requests
import traceback

from app.services.openai_service import generate_response
import re
import base64
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from typing import *
from fuzzywuzzy import fuzz
# from PIL import Image
from exif import Image as ExifImage

from enum import Enum

class UserState(Enum):
    IDLE = 0
    AWAITING_QUANTITY = 1
    AWAITING_CONFIRMATION = 2
    AWAITING_MODIFY_SELECTION = 3
    AWAITING_MODIFIED_VALUES = 4
    AWAITING_DELETE_CONFIRMATION = 5
    AWAITING_QUANTITY_DECISION = 6
    AWAITING_DELETE_FINAL_CONFIRMATION = 7  # New state for final delete confirmation
    AWAITING_RECORD_SELECTION = 8
 
    

user_states = {}
user_data = {}

scope = [
    'https://spreadsheets.google.com/feeds',
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/drive'
]
creds = ServiceAccountCredentials.from_json_keyfile_name('/Users/auggieclement/Documents/Projects/python-whatsapp-bot/plant-inventory-system-2f6e5dedb283.json', scope)
client = gspread.authorize(creds)


def log_http_response(response):
    logging.info(f"Status: {response.status_code}")
    # logging.info(f"Content-type: {response.headers.get('content-type')}")
    # logging.info(f"Body: {response.text}")


def get_text_message_input(recipient, text):
    return json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
    )


# # def generate_response(response):
# #     # Return text in uppercase
# #     return response
def handle_menu_request(sender):
    menu_message = ("🌿 Welcome to the Hacienda La Plama Plant Inventory Bot! 🌿\n\n"
                    "Here's how to use this botanical buddy:\n\n"
                    "🌱 Send a picture of a plant to add it to the inventory\n"
                    "📋 Type \"inv\" to see a list of the plants in your green collection\n"
                    "✏️ Type \"modify\" to update an existing plant record\n"
                    "🗑️ Type \"delete\" to remove a plant from the inventory\n"
                    "🔄 Type \"menu\" at any time to return to this menu")
    send_message(get_text_message_input(sender, menu_message))
    set_user_state(sender, UserState.IDLE)
    set_user_data(sender, {})  # Clear any stored user datahandle_text_message

def send_message(data):
    headers = {
        "Content-type": "application/json",
        "Authorization": f"Bearer {current_app.config['ACCESS_TOKEN']}",
    }
    print(data)
    url = f"https://graph.facebook.com/{current_app.config['VERSION']}/{current_app.config['PHONE_NUMBER_ID']}/messages"

    try:
        response = requests.post(
            url, data=data, headers=headers, timeout=10
        )  # 10 seconds timeout as an example

        response.raise_for_status()  # Raises an HTTPError if the HTTP request returned an unsuccessful status code
    except requests.Timeout:
        logging.error("Timeout occurred while sending message")
        return jsonify({"status": "error", "message": "Request timed out"}), 408
    except (
        requests.RequestException
    ) as e:  # This will catch any general request exception
        logging.error(f"Request failed due to: {e}")
        return jsonify({"status": "error", "message": "Failed to send message"}), 500
    else:
        # Process the response as normal
        log_http_response(response)
        return response


def process_text_for_whatsapp(text):
    # Remove brackets
    pattern = r"\【.*?\】"
    # Substitute the pattern with an empty string
    text = re.sub(pattern, "", text).strip()

    # Pattern to find double asterisks including the word(s) in between
    pattern = r"\*\*(.*?)\*\*"

    # Replacement pattern with single asterisks
    replacement = r"*\1*"

    # Substitute occurrences of the pattern with the replacement
    whatsapp_style_text = re.sub(pattern, replacement, text)

    return whatsapp_style_text

# def encode_image(image_path: str) -> str:
#     with open(image_path, "rb") as image_file:
#         return base64.b64encode(image_file.read()).decode('utf-8')

def extract_location_from_image(image_data: bytes) -> str:
    try:
        my_image = ExifImage('/Users/auggieclement/Desktop/WhatsApp Image 2024-08-21 at 18.10.25.jpeg')
        print(my_image.has_exif)

        # if hasattr(image, 'gps_latitude') and hasattr(image, 'gps_longitude'):
        #     lat = image.gps_latitude
        #     lon = image.gps_longitude
        #     lat_ref = image.gps_latitude_ref
        #     lon_ref = image.gps_longitude_ref
            
        #     lat = lat[0] + lat[1]/60 + lat[2]/3600
        #     lon = lon[0] + lon[1]/60 + lon[2]/3600
            
        #     if lat_ref.upper() == 'S':
        #         lat = -lat
        #     if lon_ref.upper() == 'W':
        #         lon = -lon
            
        #     return f"GPS: {lat:.6f}, {lon:.6f}"
        # else:
        #     return "Location data not available"
    except Exception as e:
        logging.error(f"Error extracting location from image: {e}")
        return "Error extracting location"
    
def retrieve_image(image_id: str) -> str:
    headers = {
        "Content-type": "application/json",
        "Authorization": f"Bearer {current_app.config['ACCESS_TOKEN']}",
    }
    media_url = f"https://graph.facebook.com/v16.0/{image_id}"

    try:
        response_media = requests.get(media_url, headers=headers)
        response_media.raise_for_status()
        json_response = response_media.json()

        media_location = json_response["url"]
        response = requests.get(media_location, headers={
            "Content-type": "image/jpeg",
            "Authorization": f"Bearer {current_app.config['ACCESS_TOKEN']}",
        })
        response.raise_for_status()

        image_data = response.content
        location = extract_location_from_image(image_data)

        return base64.b64encode(response.content).decode('utf-8'), location
    except requests.RequestException as e:
        logging.error(f"Error retrieving image: {e}")
        raise


def upload_to_inventory(sender: str, data: List[str]) -> Dict[str, Any]:
    try:
        logging.info(f"Attempting to upload to inventory with data: {data}")
        sheet = client.open('Plant Inventory').sheet1
        logging.info("Successfully connected to Google Sheet")
        
        if len(data) < 4:
            raise ValueError("Insufficient data provided")
        
        common_name, scientific_name, quantity, location = data[:4]
        
        try:
            new_quantity = int(quantity)
            if new_quantity <= 0:
                raise ValueError("Quantity must be a positive number.")
        except ValueError as e:
            logging.error(f"Invalid quantity: {quantity}")
            return get_text_message_input(sender, f"Error: {str(e)}")
        
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        logging.info("Retrieving all values from the sheet")
        values = sheet.get_all_values()
        logging.info(f"Retrieved {len(values)} rows from the sheet")
        
        logging.info(f"Searching for existing plant: {common_name} / {scientific_name}")
        existing_row = find_matching_plant(common_name, scientific_name, values)
        
        if existing_row:
            logging.info(f"Found existing plant at row {existing_row}")
            current_quantity = int(values[existing_row - 1][2])
            updated_quantity = current_quantity + new_quantity
            created_at = values[existing_row - 1][4]  # 'Created at' is in column E
            
            logging.info(f"Updating existing row with new quantity: {updated_quantity}")
            sheet.update_cell(existing_row, 3, str(updated_quantity))  # Update quantity
            sheet.update_cell(existing_row, 4, location)  # Update location
            sheet.update_cell(existing_row, 6, current_time)  # Update 'Updated at'
            
            action = "updated"
        else:
            logging.info("Plant not found. Adding new row.")
            sheet.append_row([common_name, scientific_name, str(new_quantity), location, current_time, current_time])
            updated_quantity = new_quantity
            action = "added"
        
        confirmation_message = (
            f"✅ Plant {action} in the Inventory:\n\n"
            f"🌿 Plant: {common_name}\n"
            f"🔬 Scientific name: {scientific_name}\n"
            f"🔢 Quantity: {new_quantity}\n"
            f"📍 Location: {location}\n"
            f"🕰️ {action.capitalize()} at: {current_time}\n"
        )
        
        logging.info(f"Successfully {action} plant. Sending confirmation message.")
        return get_text_message_input(sender, confirmation_message)
    except Exception as e:
        logging.error(f"Error updating inventory: {e}", exc_info=True)
        error_message = "❌ Error updating plant in inventory. Please try again."
        return get_text_message_input(sender, error_message)
    
def find_matching_plant(common_name, scientific_name, values):
    for i, row in enumerate(values):
        if (fuzz.ratio(row[0].lower(), common_name.lower()) > 90 or 
            fuzz.ratio(row[1].lower(), scientific_name.lower()) > 90):
            return i + 1
    return None

def process_plant_data(response: str) -> List[str]:
    try:
        data_response = response.split(",")
        data = [item.split(":", 1)[1].strip() for item in data_response[:3]]
        
        # Ensure we have at least 3 elements (plant name, scientific name, quantity)
        while len(data) < 3:
            data.append("Unknown")
        
        # Add location if available, otherwise use "Unknown"
        data.append(data_response[3].split(":", 1)[1].strip() if len(data_response) > 3 else "Unknown")
        
        return data
    except Exception as e:
        logging.error(f"Error processing plant data: {e}")
        logging.error(f"Response: {response}")
        return ["Unknown", "Unknown", "0", "Unknown"]
    
def get_personable_loading_message() -> str:
    messages = [
        "Hold onto your gardening gloves! 🧤 I'm taking a close look at your plant...",
        "Time for some plant magic! 🌟 Give me a moment to study this green beauty...",
        "Ooh, what do we have here? 🧐 Let me consult my virtual herbarium...",
        "Exciting! I'm channeling my inner botanist to identify your plant. Just a sec! 🌿",
        "Plant detective mode: Activated! 🕵️‍♂️🌱 I'm on the case...",
        "Wow, that's an interesting one! Let me leaf through my database... 😉🍃",
        "Nature's marvels never cease to amaze! I'm analyzing your plant now, hang tight! 🌍",
        "Photosynthesizing... I mean, analyzing your plant photo! This'll just take a moment. ☀️",
        "Branching out into my knowledge base to identify your plant. Won't be long! 🌳",
        "Rooting through my data to get you the info. Stem-sational find, by the way! 🌻"
    ]
    return random.choice(messages)


def process_whatsapp_message(body: Dict[str, Any]) -> None:
    try:
        # Log the entire body for debugging
        logging.debug(f"Received message body: {json.dumps(body, indent=2)}")

        # Check if the required keys exist
        if not body.get("entry"):
            raise KeyError("Missing 'entry' key in body")
        if not body["entry"][0].get("changes"):
            raise KeyError("Missing 'changes' key in body['entry'][0]")
        if not body["entry"][0]["changes"][0].get("value"):
            raise KeyError("Missing 'value' key in body['entry'][0]['changes'][0]")
        
        value = body["entry"][0]["changes"][0]["value"]
        
        # Check for contacts and messages
        if not value.get("contacts"):
            raise KeyError("Missing 'contacts' key in value")
        if not value.get("messages"):
            raise KeyError("Missing 'messages' key in value")

        wa_id = value["contacts"][0]["wa_id"]
        sender = value["messages"][0]["from"]
        name = value["contacts"][0]["profile"]["name"]
        message = value["messages"][0]

        if "text" in message:
            handle_text_message(message["text"]["body"], sender)
        elif "image" in message:
            handle_image_message(message["image"]["id"], wa_id, name, sender)
        else:
            logging.warning(f"Unsupported message type received from {wa_id}")
    except KeyError as e:
        logging.error(f"Error parsing message body: {e}")
        logging.debug(f"Problematic body structure: {json.dumps(body, indent=2)}")
    except Exception as e:
        logging.error(f"Unexpected error in process_whatsapp_message: {e}")
        logging.exception("Full traceback:")


def is_valid_whatsapp_message(body):
    """
    Check if the incoming webhook event has a valid WhatsApp message structure.
    """
    return (
        body.get("object")
        and body.get("entry")
        and body["entry"][0].get("changes")
        and body["entry"][0]["changes"][0].get("value")
        and body["entry"][0]["changes"][0]["value"].get("messages")
        and body["entry"][0]["changes"][0]["value"]["messages"][0]
    )



def get_user_state(user_id):
    return user_states.get(user_id, UserState.IDLE)

def set_user_state(user_id, state):
    user_states[user_id] = state

def get_user_data(user_id):
    return user_data.get(user_id, {})

def set_user_data(user_id, data):
    user_data[user_id] = data

def handle_text_message(message_body: str, sender: str) -> None:
    if message_body.lower() == "menu":
        handle_menu_request(sender)
        return
    
    state = get_user_state(sender)
    
    if state == UserState.IDLE:
        if message_body.lower() == "inv":
            inventory = get_recent_inventory()
            send_message(get_text_message_input(sender, inventory))
        elif message_body.lower() == "modify":
            handle_modify_request(sender)
        elif message_body.lower() == "delete":
            handle_delete_request(sender)
        else:
            # Your existing else logic here
            failed_message = ("🌿 Welcome to the Hacienda La Plama Plant Inventory Bot! 🌿\n\n"
                              "Here's how to use this botanical buddy:\n\n"
                              "🌱 Send a picture of a plant to add it to the inventory\n"
                              "📋 Type \"inv\" to see a list of the plants in your green collection\n"
                              "✏️ Type \"modify\" to update an existing plant record\n"
                              "🗑️ Type \"delete\" to remove a plant from the inventory\n")
            failed_payload = get_text_message_input(sender, failed_message)
            send_message(failed_payload)
    elif state == UserState.AWAITING_QUANTITY:
        handle_quantity_input(sender, message_body)
    elif state == UserState.AWAITING_CONFIRMATION:
        handle_confirmation(sender, message_body)
    elif state == UserState.AWAITING_MODIFY_SELECTION:
        handle_modify_selection(sender, message_body)
    elif state == UserState.AWAITING_MODIFIED_VALUES:
        handle_modified_values(sender, message_body)
    elif state == UserState.AWAITING_DELETE_CONFIRMATION:
        handle_delete_confirmation(sender, message_body)
    elif state == UserState.AWAITING_DELETE_FINAL_CONFIRMATION:
        handle_delete_final_confirmation(sender, message_body)
    elif state == UserState.AWAITING_QUANTITY_DECISION:
        handle_quantity_decision(sender, message_body)
    elif state == UserState.AWAITING_RECORD_SELECTION:
        handle_record_selection(sender, message_body)

def handle_record_selection(sender: str, message_body: str) -> None:
    try:
        selection = int(message_body)
        user_data = get_user_data(sender)
        inventory = user_data.get('inventory', [])
        
        if 1 <= selection <= len(inventory):
            record = inventory[selection-1]
            user_data['plant_data'] = record
            user_data['original_plant_name'] = record[0]  # Store the original plant name
            set_user_data(sender, user_data)
            send_message(get_text_message_input(sender, "What would you like to modify?\n1. Name\n2. Scientific Name\n3. Quantity\n4. Location\n5. All Values\n\nPlease enter the number of your choice."))
            set_user_state(sender, UserState.AWAITING_MODIFY_SELECTION)
        else:
            raise ValueError()
    except ValueError:
        send_message(get_text_message_input(sender, "Please enter a valid number from the list or type 'menu' to go back."))
    # send_message(get_text_message_input(sender, "What would you like to modify?\n1. Name\n2. Scientific Name\n3. Quantity\n4. Location\n5. All Values\n\nPlease enter the number of your choice."))
    # set_user_state(sender, UserState.AWAITING_MODIFY_SELECTION)

def handle_quantity_decision(sender: str, message_body: str) -> None:
    user_data = get_user_data(sender)
    plant_data = user_data.get('plant_data', [])

    if not plant_data:
        send_message(get_text_message_input(sender, "Sorry, there was an error processing the plant data. Please try again."))
        set_user_state(sender, UserState.IDLE)
        return

    if message_body == "1":
        # Use detected quantity
        confirmation_message = format_plant_data(plant_data)
        send_message(get_text_message_input(sender, f"{confirmation_message}\n\nIs this correct? (Yes/No)"))
        set_user_state(sender, UserState.AWAITING_CONFIRMATION)
    elif message_body == "2":
        # Update quantity
        send_message(get_text_message_input(sender, "Please enter the new quantity:"))
        set_user_state(sender, UserState.AWAITING_QUANTITY)
    else:
        send_message(get_text_message_input(sender, "Please respond with '1' to use the detected quantity or '2' to update it."))
        
def handle_image_message(message_body: str, wa_id: str, name: str, sender: str) -> None:
    send_message(get_text_message_input(sender, get_personable_loading_message()))

    try:
        base64_image, location = retrieve_image(message_body)
        response = generate_response(base64_image, wa_id, name)
        response = process_text_for_whatsapp(response)
        data = process_plant_data(response)
        set_user_data(sender, {
            'plant_data': data,
            'location': location,
            'is_modifying': False  # Set flag to indicate we're adding a new record
        })
        
        # Ask user about the quantity
        detected_quantity = data[2]
        quantity_message = (
            f"I've identified the plant as {data[0]} ({data[1]}).\n\n"
            f"The detected quantity is {detected_quantity}.\n"
            f"Do you want to use this quantity or update it?\n\n"
            f"1. Use detected quantity ({detected_quantity})\n"
            f"2. Update quantity"
        )
        send_message(get_text_message_input(sender, quantity_message))
        set_user_state(sender, UserState.AWAITING_QUANTITY_DECISION)
        
    except Exception as e:
        error_message = "An error occurred while processing your image. Please try again later."
        send_message(get_text_message_input(sender, error_message))
        logging.error(f"Error in handle_image_message: {e}")

## 3. Implement workflow-specific functions
def format_plant_data(data):
    formatted_data = []
    
    if len(data) > 0:
        formatted_data.append(f"🌿 Plant: {data[0]}")
    if len(data) > 1:
        formatted_data.append(f"🔬 Scientific name: {data[1]}")
    if len(data) > 2:
        formatted_data.append(f"🔢 Quantity: {data[2]}")
    if len(data) > 3:
        formatted_data.append(f"📍 Location: {data[3]}")
    else:
        formatted_data.append("📍 Location: Unknown")
    
    return "\n".join(formatted_data)


def handle_delete_confirmation(sender, message_body):
    if message_body.lower() == 'menu':
        handle_menu_request(sender)
        return

    try:
        selection = int(message_body)
        inventory = get_recent_inventory(as_list=True)
        if 1 <= selection <= len(inventory):
            record = inventory[selection-1]
            user_data = get_user_data(sender)
            user_data['delete_record'] = record
            set_user_data(sender, user_data)
            
            confirmation_message = (
                f"Are you sure you want to delete this record?\n\n"
                f"🌿 Plant: {record[0]}\n"
                f"🔬 Scientific name: {record[1]}\n"
                f"🔢 Quantity: {record[2]}\n"
                f"📍 Location: {record[3]}\n\n"
                f"Please respond with 'Yes' to confirm deletion or 'No' to cancel."
            )
            send_message(get_text_message_input(sender, confirmation_message))
            set_user_state(sender, UserState.AWAITING_DELETE_FINAL_CONFIRMATION)
        else:
            raise ValueError()
    except ValueError:
        send_message(get_text_message_input(sender, "Please enter a valid number from the list or type 'menu' to go back."))


def handle_quantity_input(sender, message_body):
    try:
        quantity = int(message_body)
        if quantity <= 0:
            raise ValueError("Quantity must be a positive number.")
        
        user_data = get_user_data(sender)
        if 'plant_data' not in user_data or not isinstance(user_data['plant_data'], list):
            raise ValueError("Invalid plant data.")
        
        # Update the quantity in the plant_data list
        if len(user_data['plant_data']) >= 3:
            user_data['plant_data'][2] = str(quantity)
        else:
            user_data['plant_data'].extend([str(quantity)] * (3 - len(user_data['plant_data'])))
        
        # Ensure location is present
        if len(user_data['plant_data']) < 4:
            user_data['plant_data'].append(user_data.get('location', 'Unknown'))
        
        set_user_data(sender, user_data)
        
        confirmation_message = format_plant_data(user_data['plant_data'])
        send_message(get_text_message_input(sender, f"{confirmation_message}\n\nIs this correct? (Yes/No)"))
        set_user_state(sender, UserState.AWAITING_CONFIRMATION)
    except ValueError as e:
        send_message(get_text_message_input(sender, f"Error: {str(e)} Please enter a valid positive number for the quantity."))
    except Exception as e:
        logging.error(f"Error in handle_quantity_input: {e}")
        send_message(get_text_message_input(sender, "An error occurred. Please try again."))

# def handle_confirmation(sender, message_body):
#     if message_body.lower() == 'yes':
#         user_data = get_user_data(sender)
#         if 'plant_data' not in user_data or not isinstance(user_data['plant_data'], list):
#             send_message(get_text_message_input(sender, "An error occurred. Please try again from the beginning."))
#             set_user_state(sender, UserState.IDLE)
#             return

#         try:
#             if user_data.get('is_modifying'):
#                 # Modifying existing record
#                 modify_inventory_record(user_data['plant_data'])
#                 confirmation_message = f"Record updated successfully:\n{format_plant_data(user_data['plant_data'])}"
#             else:
#                 # Uploading new record
#                 payload = upload_to_inventory(sender, user_data['plant_data'])
#                 send_message(payload)
#                 confirmation_message = "New record added successfully."

#             send_message(get_text_message_input(sender, confirmation_message))
#             set_user_state(sender, UserState.IDLE)
#             # Clear user data after successful operation
#             set_user_data(sender, {})
#         except Exception as e:
#             logging.error(f"Error in handling inventory operation: {e}")
#             send_message(get_text_message_input(sender, "An error occurred while updating the inventory. Please try again."))
#     elif message_body.lower() == 'no':
#         send_message(get_text_message_input(sender, "What would you like to modify?\n1. Name\n2. Scientific Name\n3. Quantity\n4. Location\n5. All Values\n\nPlease enter the number of your choice."))
#         set_user_state(sender, UserState.AWAITING_MODIFY_SELECTION)
#     else:
#         send_message(get_text_message_input(sender, "Please respond with 'Yes' or 'No'."))


def handle_modify_request(sender):
    inventory_list = get_recent_inventory(as_list=True)


    inventory = get_recent_inventory()
    inventory += "\nWhich record would you like to modify? (Enter the number)"
    send_message(get_text_message_input(sender, inventory))
    
    set_user_state(sender, UserState.AWAITING_RECORD_SELECTION)
    user_data = get_user_data(sender)
    user_data['is_modifying'] = True
    user_data['inventory'] = inventory_list
    set_user_data(sender, user_data)


def handle_modify_selection(sender, message_body):
    try:
        selection = int(message_body)
        if 1 <= selection <= 5:
            attributes = ['Name', 'Scientific Name', 'Quantity', 'Location', 'All Values']
            selected_attribute = attributes[selection - 1]
            user_data = get_user_data(sender)
            user_data['selected_attribute'] = selected_attribute.lower()
            set_user_data(sender, user_data)
            
            if selected_attribute == 'All Values':
                current_data = user_data.get('plant_data', ['', '', '', ''])
                prompt = (f"Please enter new values for all fields, separated by commas.\n"
                          f"Current values:\n"
                          f"1. Name: {current_data[0]}\n"
                          f"2. Scientific Name: {current_data[1]}\n"
                          f"3. Quantity: {current_data[2]}\n"
                          f"4. Location: {current_data[3]}\n\n"
                          f"Enter new values (Name, Scientific Name, Quantity, Location):")
            else:
                prompt = f"Please enter the new value for {selected_attribute}:"
            
            send_message(get_text_message_input(sender, prompt))
            set_user_state(sender, UserState.AWAITING_MODIFIED_VALUES)
        else:
            raise ValueError()
    except ValueError:
        send_message(get_text_message_input(sender, "Please enter a valid number (1-5) corresponding to the attribute you want to modify."))



def handle_attribute_selection(sender, message_body):
    attributes = ['name', 'scientific name', 'quantity', 'location']
    if message_body.lower() in attributes:
        user_data = get_user_data(sender)
        user_data['selected_attribute'] = message_body.lower()
        set_user_data(sender, user_data)
        send_message(get_text_message_input(sender, f"Please enter the new value for {message_body}:"))
        set_user_state(sender, UserState.AWAITING_MODIFIED_VALUE)
    else:
        send_message(get_text_message_input(sender, "Please select a valid attribute (Name/Scientific Name/Quantity/Location)."))



def handle_modified_values(sender, message_body):
    user_data = get_user_data(sender)
    selected_attribute = user_data.get('selected_attribute')
    plant_data = user_data.get('plant_data', ['', '', '', ''])

    if not selected_attribute:
        send_message(get_text_message_input(sender, "An error occurred. Please try again from the beginning."))
        set_user_state(sender, UserState.IDLE)
        return

    if selected_attribute == 'all values':
        new_values = [v.strip() for v in message_body.split(',')]
        if len(new_values) != 4:
            send_message(get_text_message_input(sender, "Please provide all 4 values separated by commas."))
            return
        try:
            quantity = int(new_values[2])
            if quantity <= 0:
                raise ValueError()
            plant_data = new_values
        except ValueError:
            send_message(get_text_message_input(sender, "Please enter a valid positive number for the quantity."))
            return
    else:
        attribute_index = ['name', 'scientific name', 'quantity', 'location'].index(selected_attribute)
        if attribute_index == 2:  # Quantity
            try:
                new_value = int(message_body)
                if new_value <= 0:
                    raise ValueError()
            except ValueError:
                send_message(get_text_message_input(sender, "Please enter a valid positive number for the quantity."))
                return
        else:
            new_value = message_body
        plant_data[attribute_index] = str(new_value)

    user_data['plant_data'] = plant_data
    set_user_data(sender, user_data)

    confirmation_message = format_plant_data(plant_data)
    send_message(get_text_message_input(sender, f"{confirmation_message}\n\nIs this correct? (Yes/No)"))
    set_user_state(sender, UserState.AWAITING_CONFIRMATION)


def handle_delete_request(sender):
    inventory = get_recent_inventory()
    send_message(get_text_message_input(sender, f"{inventory}\n\nWhich record would you like to delete? (Enter the number)"))
    set_user_state(sender, UserState.AWAITING_DELETE_CONFIRMATION)


def get_inventory(sort_by_recency=False):
    try:
        sheet = client.open('Plant Inventory').sheet1
        values = sheet.get_all_values()
        
        if not values:
            return "The inventory is empty. 🌱"
        
        headers = values[0]
        inventory = values[1:]
        
        if sort_by_recency:
            inventory.sort(key=lambda x: x[5], reverse=True)  # Assuming column F is 'Updated at'
        
        inventory_str = "🌿 *Plant Inventory* 🌿\n\n"
        for index, item in enumerate(inventory, start=1):
            inventory_str += f"*{index}.* "
            plant_details = []
            for i, header in enumerate(headers):
                if item[i] and header.lower() in ['common name', 'scientific name', 'quantity', 'location']:
                    plant_details.append(f"{header}: {item[i]}")
            inventory_str += " | ".join(plant_details) + "\n"
        
        inventory_str += f"\nTotal plants: {len(inventory)} 🌳"
        
        return inventory_str
    except Exception as e:
        logging.error(f"Error retrieving inventory: {e}")
        return "Error retrieving inventory. Please try again later. 😕"
def get_recent_inventory(as_list=False):
    try:
        sheet = client.open('Plant Inventory').sheet1
        values = sheet.get_all_values()
        
        if not values:
            return [] if as_list else "The inventory is empty. 🌱"
        
        headers = values[0]
        inventory = values[1:]  # Exclude header
        
        # Sort by 'Updated at' column (assuming it's the 6th column, index 5)
        sorted_values = sorted(inventory, key=lambda x: x[5], reverse=True)
        
        if as_list:
            return sorted_values
        
        inventory_str = "🌿 *Recent Plant Inventory* 🌿\n\n"
        for index, item in enumerate(sorted_values, start=1):
            inventory_str += f"*{index}.* {item[0]} ({item[1]}) - Qty: {item[2]}, Location: {item[3]}\n"
        
        return inventory_str
    except Exception as e:
        logging.error(f"Error retrieving recent inventory: {e}")
        return [] if as_list else "Error retrieving inventory. Please try again later. 😕"
    
    
def modify_inventory_record(user_data):
    try:
        sheet = client.open('Plant Inventory').sheet1
        record = user_data['plant_data']
        logging.info(f"Searching for record to modify: {user_data['original_plant_name']}")
        cell_list = sheet.findall(user_data['original_plant_name'])  # Find by plant name
        
        if not cell_list:
            logging.error(f"No matching records found for: {user_data['original_plant_name']}")
            raise Exception(f"Record not found in the inventory: {user_data['original_plant_name']}")
        
        # Sort cell_list by the 'Updated at' column (assuming it's column 6)
        sorted_cells = sorted(cell_list, key=lambda c: sheet.cell(c.row, 6).value, reverse=True)
        
        if not sorted_cells:
            logging.error(f"Failed to sort matching records for: {user_data['original_plant_name']}")
            raise Exception(f"Failed to process matching records for: {user_data['original_plant_name']}")
        
        cell = sorted_cells[0]  # Get the most recently updated cell
        
        if cell is None:
            logging.error(f"Failed to get the most recent record for: {user_data['original_plant_name']}")
            raise Exception(f"Failed to retrieve the record for: {user_data['original_plant_name']}")
        
        logging.info(f"Found record to modify at row {cell.row}")
        
        # Update the cells
        sheet.update_cell(cell.row, 1, record[0])  # Name
        sheet.update_cell(cell.row, 2, record[1])  # Scientific Name
        sheet.update_cell(cell.row, 3, record[2])  # Quantity
        sheet.update_cell(cell.row, 4, record[3])  # Location
        sheet.update_cell(cell.row, 6, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))  # Updated at
        
        logging.info(f"Successfully updated record: {record[0]}")
    except Exception as e:
        logging.error(f"Error modifying inventory record: {str(e)}")
        logging.error(traceback.format_exc())
        raise


def handle_confirmation(sender, message_body):
    if message_body.lower() == 'yes':
        user_data = get_user_data(sender)
        if 'plant_data' not in user_data or not isinstance(user_data['plant_data'], list):
            logging.error(f"Invalid user_data: {user_data}")
            send_message(get_text_message_input(sender, "An error occurred. Please try again from the beginning."))
            set_user_state(sender, UserState.IDLE)
            return

        try:
            if user_data.get('is_modifying'):
                logging.info(f"Attempting to modify record: {user_data['original_plant_name']}")
                modify_inventory_record(user_data)
                confirmation_message = f"Record updated successfully:\n{format_plant_data(user_data['plant_data'])}"
            else:
                logging.info(f"Attempting to upload new record: {user_data['plant_data']}")
                payload = upload_to_inventory(sender, user_data['plant_data'])
                send_message(payload)
                confirmation_message = "New record added successfully."

            send_message(get_text_message_input(sender, confirmation_message))
            set_user_state(sender, UserState.IDLE)
            set_user_data(sender, {})
        except Exception as e:
            logging.error(f"Error in handling inventory operation: {str(e)}")
            logging.error(traceback.format_exc())
            send_message(get_text_message_input(sender, "An error occurred while updating the inventory. Please try again."))
    elif message_body.lower() == 'no':
        send_message(get_text_message_input(sender, "What would you like to modify?\n1. Name\n2. Scientific Name\n3. Quantity\n4. Location\n5. All Values\n\nPlease enter the number of your choice."))
        set_user_state(sender, UserState.AWAITING_MODIFY_SELECTION)
    else:
        send_message(get_text_message_input(sender, "Please respond with 'Yes' or 'No'."))

def handle_delete_final_confirmation(sender, message_body):
    if message_body.lower() == 'yes':
        user_data = get_user_data(sender)
        record = user_data.get('delete_record')
        
        if not record:
            send_message(get_text_message_input(sender, "An error occurred. Please try the delete process again."))
            set_user_state(sender, UserState.IDLE)
            return
        
        # Show loading message
        send_message(get_text_message_input(sender, "Deleting record... Please wait."))
        
        # Attempt to delete the record
        success, message = delete_inventory_record(record)
        
        if success:
            send_message(get_text_message_input(sender, "Record deleted successfully!"))
            # Show updated inventory
            inventory = get_recent_inventory()
            send_message(get_text_message_input(sender, inventory))
        else:
            send_message(get_text_message_input(sender, f"An error occurred while trying to delete the record: {message}"))
    elif message_body.lower() == 'no':
        send_message(get_text_message_input(sender, "Deletion cancelled. The record was not deleted."))
    else:
        send_message(get_text_message_input(sender, "Please respond with 'Yes' to confirm deletion or 'No' to cancel."))
        return
    
    # Clear the stored record and reset state
    user_data = get_user_data(sender)
    user_data.pop('delete_record', None)
    set_user_data(sender, user_data)
    set_user_state(sender, UserState.IDLE)

def delete_inventory_record(record):
    try:
        sheet = client.open('Plant Inventory').sheet1
        cell = sheet.find(record[0])  # Find by plant name
        
        if not cell:
            logging.error(f"Record not found: {record[0]}")
            return False, "Record not found in the inventory."
        
        # Get all values
        values = sheet.get_all_values()
        
        # Remove the row
        del values[cell.row - 1]
        
        # Clear the entire sheet
        sheet.clear()
        
        # Re-add the header if it exists
        if len(values) > 0:
            sheet.insert_row(values[0], 1)
            
            # Add the rest of the data
            sheet.insert_rows(values[1:], 2)
        
        logging.info(f"Successfully deleted record: {record[0]}")
        return True, "Record deleted successfully."
    except Exception as e:
        error_msg = f"Error deleting inventory record: {str(e)}"
        logging.error(error_msg)
        # logging.error(traceback.format_exc())  # Log the full stack trace
        return False, error_msg