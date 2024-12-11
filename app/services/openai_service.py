from openai import OpenAI
import shelve
from dotenv import load_dotenv
import os
import time
import logging
from flask import current_app
import base64
import requests

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_ASSISTANT_ID = os.getenv("OPENAI_ASSISTANT_ID")
client = OpenAI(api_key=OPENAI_API_KEY)


def upload_file(path):
    # Upload a file with an "assistants" purpose
    file = client.files.create(
        file=open("../../data/airbnb-faq.pdf", "rb"), purpose="assistants"
    )


def create_assistant(file):
    """
    You currently cannot set the temperature for Assistant via the API.
    """
    assistant = client.beta.assistants.create(
        name="WhatsApp AirBnb Assistant",
        instructions="You are a Helpful Plant Inventory bot. You will only accept pictures of plants and respond back with helpful information regarding the plant. If a user asks for other information, Let the user know that you can only accept Pictures of plants.",
        # tools=[{"type": "retrieval"}],
        model="gpt-4o-mini",
        # file_ids=[file.id],
    )
    return assistant


# Use context manager to ensure the shelf file is closed properly
def check_if_thread_exists(wa_id):
    with shelve.open("threads_db") as threads_shelf:
        return threads_shelf.get(wa_id, None)


def store_thread(wa_id, thread_id):
    with shelve.open("threads_db", writeback=True) as threads_shelf:
        threads_shelf[wa_id] = thread_id


def run_assistant(thread, name):
    # Retrieve the Assistant
    assistant = client.beta.assistants.retrieve(OPENAI_ASSISTANT_ID)

    # Run the assistant
    run = client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=assistant.id,
        # instructions=f"You are having a conversation with {name}",
    )

    # Wait for completion
    # https://platform.openai.com/docs/assistants/how-it-works/runs-and-run-steps#:~:text=under%20failed_at.-,Polling%20for%20updates,-In%20order%20to
    while run.status != "completed":
        # Be nice to the API
        time.sleep(0.5)
        run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)

    # Retrieve the Messages
    messages = client.beta.threads.messages.list(thread_id=thread.id)
    new_message = messages.data[0].content[0].text.value
    logging.info(f"Generated message: {new_message}")
    return new_message


def generate_response(message_body, wa_id, name):

    headers = {
    # "Content-Type": "image/jpeg",
    "Authorization": f"Bearer {OPENAI_API_KEY}"
    }

    payload = {
    "model": "gpt-4o",
    "messages": [
    {
        "role": "system",
        "content": "You are a Helpful Plant Identifier Assistant. I will take base64 encoded images and analyze the image after decoding the content and identify what species of plants are in the image. I will only identify the species of plant and the quantity. I will not help the user on any other issues. I will respond with only the regular plant name and scientific name and quanity in the image. All these plants are found in Costa Rica. Use this structure -  Common Name: namehere, Scientific Name: namehere, Quantity: name here"        
    },
    {
        "role": "user",
        "content": [
        {
             "type": "image_url",
            "image_url": {
            "url": f"data:image/jpeg;base64,{message_body}"
            }
            },
       
        ]
    },
        ],
    
    "max_tokens": 300
    }
    response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
    plant_type = response.json()

    message_content = plant_type['choices'][0]['message']['content']


    # print(message)

    # Run the assistant and get the new message
    # new_message = run_assistant(thread, name)

    return message_content
