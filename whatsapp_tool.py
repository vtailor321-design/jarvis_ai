import time
from playwright.sync_api import sync_playwright

# Apne main contacts yahan add kar lo (mic surname galat sune toh bhi sahi naam pakad lega)
CONTACTS = {
    "daksh": "Daksh Nuwal",
    "abhishek": "Abhishek Ashirwal",
}

def resolve_contact(name):
    name_lower = name.lower()
    for key, real_name in CONTACTS.items():
        if key in name_lower:
            return real_name
    return name

def send_whatsapp_message(contact_name, message):
    contact_name = resolve_contact(contact_name)
    print(f"📲 WhatsApp open kar rahi hoon -> {contact_name}: {message}")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                user_data_dir="./whatsapp_session",
                headless=False
            )
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.goto("https://web.whatsapp.com")

            # 1. Naye WhatsApp Web ka Search Box dhoondho
            print("⏳ WhatsApp load ho raha hai...")
            search_box = page.get_by_placeholder("Search or start a new chat").or_(
                page.get_by_text("Search or start a new chat")
            ).first
            search_box.wait_for(timeout=60000)
            time.sleep(2)

            # 2. Contact search karo
            print(f"🔍 '{contact_name}' ko search kar rahi hoon...")
            search_box.click()
            page.keyboard.type(contact_name, delay=80)
            time.sleep(2.5)
            page.keyboard.press("Enter")
            time.sleep(2)

            # 3. Message box mein type karke bhejo
            print("✍️ Message type kar rahi hoon...")
            msg_box = page.locator('footer div[contenteditable="true"]').first
            msg_box.wait_for(timeout=15000)
            msg_box.click()
            page.keyboard.type(message, delay=40)
            time.sleep(1)

            # Direct Send button click karo (fallback: Enter key)
            send_btn = page.locator('button[aria-label="Send"], span[data-icon="send"]').first
            if send_btn.is_visible():
                send_btn.click()
            else:
                page.keyboard.press("Enter")

            print("⏳ Message deliver (tick) hone ka wait kar raha hoon...")
            time.sleep(10)  # Message bubble screen par aane ka wait

            # Jab tak clock icon (msg-time) dikh raha hai, window band mat karo (max 30 sec)
            for _ in range(30):
                pending = page.locator('span[data-icon="msg-time"]').count()
                if pending == 0:
                    break
                time.sleep(10)

            time.sleep(10)  # Final sync buffer
            print("✅ Message deliver ho gaya!")
            browser.close()
            return f"Success: {contact_name} ko message bhej diya."
    except Exception as e:
        print(f"❌ WhatsApp Error: {e}")
        return f"Error: Message nahi ja paya ({e})"