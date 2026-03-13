import json
import requests
import streamlit as st
import time
import uuid
from datetime import datetime
from pathlib import Path


API_URL = "https://router.huggingface.co/v1/chat/completions"
MODEL_NAME = "meta-llama/Llama-3.2-1B-Instruct"
REQUEST_TIMEOUT = 30
SYSTEM_PROMPT = "You are a helpful AI assistant."
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
CHAT_DIRECTORY = Path("chats")
MEMORY_FILE = Path("memory.json")
STREAM_DELAY_SECONDS = 0.02
PART_A_TEST_MESSAGE = "Hello!"


def get_hf_token():
    """Safely load the Hugging Face token from Streamlit secrets."""
    try:
        token = st.secrets["HF_TOKEN"]
    except Exception:
        return None

    if isinstance(token, str):
        token = token.strip()

    return token or None


def build_headers(token):
    """Create request headers for the Hugging Face Inference Router."""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def initialize_session_state():
    """Create the chat containers used by the app."""
    if "chats" not in st.session_state:
        chats = load_chats_from_disk()
        if not chats:
            first_chat = create_new_chat()
            chats = [first_chat]
            save_chat_to_disk(first_chat)

        st.session_state.chats = chats
        st.session_state.active_chat_id = chats[0]["id"]

    if "memory_items" not in st.session_state:
        st.session_state.memory_items = load_memory_from_disk()


def create_new_chat():
    """Create a new empty chat record."""
    timestamp = datetime.now().strftime(TIMESTAMP_FORMAT)
    return {
        "id": str(uuid.uuid4()),
        "title": f"New Chat {timestamp}",
        "created_at": timestamp,
        "messages": [],
    }


def get_chat_file_path(chat_id):
    """Build the JSON file path for a chat."""
    return CHAT_DIRECTORY / f"{chat_id}.json"


def ensure_chat_directory():
    """Create the chats directory if it does not exist."""
    CHAT_DIRECTORY.mkdir(parents=True, exist_ok=True)


def normalize_chat(chat_data):
    """Validate and normalize chat data loaded from JSON."""
    if not isinstance(chat_data, dict):
        return None

    chat_id = str(chat_data.get("id", "")).strip()
    title = str(chat_data.get("title", "")).strip()
    created_at = str(chat_data.get("created_at", "")).strip()
    messages = chat_data.get("messages", [])

    if not chat_id or not created_at or not isinstance(messages, list):
        return None

    normalized_messages = []
    for message in messages:
        if not isinstance(message, dict):
            continue

        role = str(message.get("role", "")).strip()
        content = str(message.get("content", "")).strip()
        if role in {"user", "assistant"} and content:
            normalized_messages.append({"role": role, "content": content})

    if not title:
        title = f"Chat {created_at}"

    return {
        "id": chat_id,
        "title": title,
        "created_at": created_at,
        "messages": normalized_messages,
    }


def load_chats_from_disk():
    """Load all saved chat JSON files from the chats directory."""
    ensure_chat_directory()
    chats = []

    for file_path in sorted(CHAT_DIRECTORY.glob("*.json")):
        try:
            with file_path.open("r", encoding="utf-8") as file:
                chat_data = json.load(file)
        except (OSError, json.JSONDecodeError):
            continue

        normalized_chat = normalize_chat(chat_data)
        if normalized_chat:
            chats.append(normalized_chat)

    chats.sort(key=lambda chat: chat["created_at"], reverse=True)
    return chats


def save_chat_to_disk(chat):
    """Save one chat as a separate JSON file."""
    ensure_chat_directory()
    file_path = get_chat_file_path(chat["id"])
    chat_payload = {
        "id": chat["id"],
        "title": chat["title"],
        "created_at": chat["created_at"],
        "messages": chat["messages"],
    }

    try:
        with file_path.open("w", encoding="utf-8") as file:
            json.dump(chat_payload, file, indent=2)
    except OSError:
        st.error(f"Could not save chat file: {file_path.name}")


def delete_chat_file(chat_id):
    """Delete the JSON file for a chat if it exists."""
    file_path = get_chat_file_path(chat_id)
    try:
        if file_path.exists():
            file_path.unlink()
    except OSError:
        st.error(f"Could not delete chat file: {file_path.name}")


def normalize_memory_items(memory_data):
    """Convert memory file data into a safe list of strings."""
    if isinstance(memory_data, dict):
        memory_data = memory_data.get("memories", [])

    if not isinstance(memory_data, list):
        return []

    normalized_items = []
    seen_items = set()

    for item in memory_data:
        text = str(item).strip()
        if text and text not in seen_items:
            normalized_items.append(text)
            seen_items.add(text)

    return normalized_items


def load_memory_from_disk():
    """Load saved user memory from memory.json."""
    if not MEMORY_FILE.exists():
        return []

    try:
        with MEMORY_FILE.open("r", encoding="utf-8") as file:
            memory_data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return []

    return normalize_memory_items(memory_data)


def save_memory_to_disk(memory_items):
    """Save user memory to memory.json."""
    payload = {"memories": memory_items}

    try:
        with MEMORY_FILE.open("w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2)
    except OSError:
        st.error("Could not save memory.json")


def clear_memory():
    """Reset stored user memory."""
    st.session_state.memory_items = []
    save_memory_to_disk(st.session_state.memory_items)


def get_active_chat():
    """Return the currently selected chat dictionary."""
    active_chat_id = st.session_state.get("active_chat_id")
    for chat in st.session_state.chats:
        if chat["id"] == active_chat_id:
            return chat

    if st.session_state.chats:
        st.session_state.active_chat_id = st.session_state.chats[0]["id"]
        return st.session_state.chats[0]

    return None


def make_chat_title(first_message, created_at):
    """Generate a simple chat title from the first user message."""
    cleaned_text = " ".join(first_message.strip().split())
    if not cleaned_text:
        return f"Chat {created_at}"

    max_length = 40
    if len(cleaned_text) <= max_length:
        return cleaned_text

    return f"{cleaned_text[:max_length].rstrip()}..."


def update_chat_title(chat, user_message):
    """Replace the default title once the chat gets its first user message."""
    default_title = f"New Chat {chat['created_at']}"
    if len(chat["messages"]) == 1 and chat["title"] == default_title:
        chat["title"] = make_chat_title(user_message, chat["created_at"])
        save_chat_to_disk(chat)


def create_chat():
    """Add a new chat and make it the active one."""
    new_chat = create_new_chat()
    st.session_state.chats.insert(0, new_chat)
    st.session_state.active_chat_id = new_chat["id"]
    save_chat_to_disk(new_chat)


def switch_chat(chat_id):
    """Switch the active chat without changing any messages."""
    st.session_state.active_chat_id = chat_id


def delete_chat(chat_id):
    """Delete a chat and choose a safe next active chat."""
    chats = st.session_state.chats
    delete_index = None

    for index, chat in enumerate(chats):
        if chat["id"] == chat_id:
            delete_index = index
            break

    if delete_index is None:
        return

    was_active = st.session_state.active_chat_id == chat_id
    chats.pop(delete_index)
    delete_chat_file(chat_id)

    if not chats:
        st.session_state.active_chat_id = None
        return

    if was_active:
        next_index = min(delete_index, len(chats) - 1)
        st.session_state.active_chat_id = chats[next_index]["id"]


def build_payload(messages):
    """Create the API payload using the full conversation history."""
    return {
        "model": MODEL_NAME,
        "messages": messages,
        "stream": True,
    }


def build_non_streaming_payload(messages):
    """Create a standard JSON chat payload."""
    return {
        "model": MODEL_NAME,
        "messages": messages,
        "stream": False,
    }


def build_part_a_test_messages():
    """Create the required Part A hardcoded Hello test message."""
    return [{"role": "user", "content": PART_A_TEST_MESSAGE}]


def parse_response_text(response_json):
    """Extract the assistant text from a successful API response."""
    try:
        return response_json["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError):
        return None


def get_api_error_message(response):
    """Read a useful error message from a failed API response."""
    try:
        error_json = response.json()
        error_message = error_json.get("error") or error_json.get("message")
    except ValueError:
        error_message = response.text.strip()

    if not error_message:
        error_message = f"HTTP {response.status_code}"

    return error_message


def stream_chat_response(token, messages):
    """Stream the assistant reply from the Hugging Face API."""
    try:
        response = requests.post(
            API_URL,
            headers=build_headers(token),
            json=build_payload(messages),
            timeout=REQUEST_TIMEOUT,
            stream=True,
        )
    except requests.exceptions.Timeout:
        return False, "The request timed out. Please try again in a moment."
    except requests.exceptions.ConnectionError:
        return (
            False,
            "A network error occurred while contacting the Hugging Face API.",
        )
    except requests.exceptions.RequestException as error:
        return False, f"Request failed: {error}"

    if response.status_code == 401:
        return False, "Invalid Hugging Face token. Check `HF_TOKEN` in your secrets."

    if response.status_code == 429:
        return False, "Rate limit reached. Wait a moment, then rerun the app."

    if not response.ok:
        return False, f"API request failed: {get_api_error_message(response)}"

    return True, response


def request_json_chat_response(token, messages):
    """Send a non-streaming chat request and return the parsed JSON."""
    try:
        response = requests.post(
            API_URL,
            headers=build_headers(token),
            json=build_non_streaming_payload(messages),
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.RequestException:
        return False, None

    if not response.ok:
        return False, None

    try:
        return True, response.json()
    except ValueError:
        return False, None


def run_part_a_test(token):
    """Run the required hardcoded Hello test and return the assistant text."""
    success, response_json = request_json_chat_response(
        token, build_part_a_test_messages()
    )
    if not success or not response_json:
        return False, "The Part A test request failed."

    response_text = extract_message_text(response_json)
    if not response_text:
        return False, "The Part A test did not return assistant text."

    return True, response_text


def extract_stream_delta(event_data):
    """Extract incremental text from one SSE event payload."""
    try:
        payload = json.loads(event_data)
    except json.JSONDecodeError:
        return None

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None

    delta = choices[0].get("delta", {})
    if not isinstance(delta, dict):
        return None

    content = delta.get("content")
    if isinstance(content, str):
        return content

    return None


def stream_assistant_text(response, placeholder):
    """Render streaming text in Streamlit and return the final full response."""
    chunks = []

    try:
        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue

            line = raw_line.strip()
            if not line.startswith("data:"):
                continue

            event_data = line[5:].strip()
            if event_data == "[DONE]":
                break

            chunk = extract_stream_delta(event_data)
            if chunk:
                chunks.append(chunk)
                placeholder.markdown("".join(chunks))
                time.sleep(STREAM_DELAY_SECONDS)
    except requests.exceptions.RequestException:
        return False, "The response stream was interrupted."
    finally:
        response.close()

    full_response = "".join(chunks).strip()
    if not full_response:
        return False, "The API response did not contain assistant text."

    placeholder.markdown(full_response)
    return True, full_response


def extract_message_text(response_json):
    """Read the assistant text from a non-streaming response body."""
    try:
        return response_json["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError):
        return None


def build_memory_context():
    """Format stored memory as prompt text for future replies."""
    memory_items = st.session_state.memory_items
    if not memory_items:
        return ""

    return "Known user memory:\n- " + "\n- ".join(memory_items)


def build_memory_extraction_messages(user_message):
    """Create the lightweight prompt for extracting useful user memory."""
    return [
        {
            "role": "system",
            "content": (
                "Extract lasting user facts or preferences from the user's message. "
                "Return JSON only in this format: "
                '{"memories":["fact 1","fact 2"]}. '
                "If nothing useful should be stored, return "
                '{"memories":[]}.'
            ),
        },
        {
            "role": "user",
            "content": f"User message: {user_message}",
        },
    ]


def merge_memory_items(existing_items, new_items):
    """Merge new memory items without duplicates."""
    merged_items = []
    seen_items = set()

    for item in existing_items + new_items:
        text = str(item).strip()
        if text and text not in seen_items:
            merged_items.append(text)
            seen_items.add(text)

    return merged_items


def update_user_memory(token, user_message):
    """Extract and save memory items from the latest user message."""
    success, response_json = request_json_chat_response(
        token, build_memory_extraction_messages(user_message)
    )
    if not success or not response_json:
        return

    response_text = extract_message_text(response_json)
    if not response_text:
        return

    try:
        memory_payload = json.loads(response_text)
    except json.JSONDecodeError:
        return

    new_items = normalize_memory_items(memory_payload)
    if not new_items:
        return

    st.session_state.memory_items = merge_memory_items(
        st.session_state.memory_items, new_items
    )
    save_memory_to_disk(st.session_state.memory_items)


def render_chat_history():
    """Show the full conversation above the input box."""
    active_chat = get_active_chat()
    if not active_chat:
        st.info("No chats yet. Create a new chat from the sidebar.")
        return

    if not active_chat["messages"]:
        st.info("Start the conversation by sending your first message.")
        return

    for message in active_chat["messages"]:
        with st.chat_message(message["role"]):
            st.write(message["content"])


def build_api_messages():
    """Build the message list sent to the model, including a simple system prompt."""
    system_parts = [SYSTEM_PROMPT]
    memory_context = build_memory_context()
    if memory_context:
        system_parts.append(memory_context)

    api_messages = [{"role": "system", "content": "\n\n".join(system_parts)}]
    active_chat = get_active_chat()
    if active_chat:
        api_messages.extend(active_chat["messages"])
    return api_messages


def handle_user_input(token):
    """Collect user input, call the API, and store both sides of the conversation."""
    active_chat = get_active_chat()
    if not active_chat:
        st.chat_input("Type your message here", disabled=True)
        return

    prompt = st.chat_input("Type your message here")
    if not prompt:
        return

    user_message = {"role": "user", "content": prompt}
    active_chat["messages"].append(user_message)
    update_chat_title(active_chat, prompt)
    save_chat_to_disk(active_chat)

    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        success, result = stream_chat_response(token, build_api_messages())

        if success:
            stream_success, streamed_text = stream_assistant_text(result, placeholder)
            if stream_success:
                active_chat["messages"].append(
                    {"role": "assistant", "content": streamed_text}
                )
                save_chat_to_disk(active_chat)
                update_user_memory(token, prompt)
            else:
                placeholder.empty()
                st.error(streamed_text)
                active_chat["messages"].pop()
                save_chat_to_disk(active_chat)
        else:
            st.error(result)
            active_chat["messages"].pop()
            save_chat_to_disk(active_chat)


def render_sidebar():
    """Render chat management controls in the native Streamlit sidebar."""
    with st.sidebar:
        st.header("Chats")

        if st.button("New Chat", use_container_width=True):
            create_chat()
            st.rerun()

        if not st.session_state.chats:
            st.info("No chats available.")
            return

        for chat in st.session_state.chats:
            is_active = chat["id"] == st.session_state.active_chat_id
            chat_label = chat["title"]
            if is_active:
                chat_label = f"▶ {chat_label}"

            st.caption(chat["created_at"])
            columns = st.columns([5, 1])

            with columns[0]:
                if st.button(
                    chat_label,
                    key=f"select_{chat['id']}",
                    use_container_width=True,
                ):
                    switch_chat(chat["id"])
                    st.rerun()

            with columns[1]:
                if st.button("X", key=f"delete_{chat['id']}", use_container_width=True):
                    delete_chat(chat["id"])
                    st.rerun()

        with st.expander("User Memory", expanded=True):
            if st.session_state.memory_items:
                for item in st.session_state.memory_items:
                    st.write(f"- {item}")
            else:
                st.write("No saved memory yet.")

            if st.button("Clear Memory", use_container_width=True):
                clear_memory()
                st.rerun()


def render_part_a_test(token):
    """Keep the original Part A Hello test visible in the final app."""
    with st.expander("Part A API Test", expanded=False):
        st.write(f"Test message: `{PART_A_TEST_MESSAGE}`")

        if st.button("Run Hello Test", use_container_width=False):
            with st.spinner("Sending hardcoded Hello test..."):
                success, result = run_part_a_test(token)

            if success:
                st.success("Part A test succeeded.")
                st.write(result)
            else:
                st.error(result)


def main():
    st.set_page_config(page_title="My AI Chat", layout="wide")
    st.title("My AI Chat")
    st.caption("User Memory: streaming multi-chat app with saved user traits")

    initialize_session_state()
    render_sidebar()

    token = get_hf_token()
    if not token:
        st.error(
            "Missing Hugging Face token. Add `HF_TOKEN` to `.streamlit/secrets.toml` "
            "before running the app."
        )
        return

    st.write(f"Model: `{MODEL_NAME}`")
    render_part_a_test(token)
    render_chat_history()
    handle_user_input(token)


if __name__ == "__main__":
    main()
