// ==========================================
// 1. الإعدادات والمتغيرات الأساسية
// ==========================================
const BASE_URL = "https://bob-2-production.up.railway.app";
const LOGIN_URL = `${BASE_URL}/api/v1/auth/login`; 
const CHAT_URL = `${BASE_URL}/api/v1/erp/chat-spreadsheet`;

// عناصر واجهة تسجيل الدخول
const loginScreen = document.getElementById("login-screen");
const loginForm = document.getElementById("login-form");
const usernameInput = document.getElementById("username");
const passwordInput = document.getElementById("password");
const loginError = document.getElementById("login-error");

// عناصر واجهة المحادثة
const chatScreen = document.getElementById("chat-screen");
const chatBox = document.getElementById("chat-box");
const userInput = document.getElementById("user-input");
const fileInput = document.getElementById("file-input");
const sendBtn = document.getElementById("send-btn");
const logoutBtn = document.getElementById("logout-btn");

// ==========================================
// 2. إدارة الجلسة (Session Management)
// ==========================================

document.addEventListener("DOMContentLoaded", () => {
    const savedToken = localStorage.getItem("bob2_token");
    if (savedToken) {
        showChatScreen();
    } else {
        showLoginScreen();
    }
});

function showLoginScreen() {
    loginScreen.classList.remove("hidden");
    chatScreen.classList.add("hidden");
}

function showChatScreen() {
    loginScreen.classList.add("hidden");
    chatScreen.classList.remove("hidden");
}

logoutBtn.addEventListener("click", () => {
    localStorage.removeItem("bob2_token");
    showLoginScreen();
});

// ==========================================
// 3. دالة تسجيل الدخول (Fetch Auth Token)
// ==========================================
loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    loginError.classList.add("hidden"); 

    const username = usernameInput.value.trim();
    const password = passwordInput.value.trim();

    // التعديل السحري هنا: تغيير username إلى email بناءً على طلب السيرفر
    const loginData = {
        email: username, 
        password: password
    };

    try {
        const response = await fetch(LOGIN_URL, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(loginData)
        });

        if (response.status === 422) {
            const errorData = await response.json();
            const exactReason = JSON.stringify(errorData.detail || errorData);
            throw new Error(`خطأ 422 - تفاصيل الباك إند: ${exactReason}`);
        }

        if (!response.ok) {
            throw new Error(`خطأ ${response.status}: البريد الإلكتروني أو كلمة المرور غير صحيحة.`);
        }

        const data = await response.json();
        const token = data.access_token || data.token;

        if (token) {
            localStorage.setItem("bob2_token", token);
            showChatScreen();
        } else {
            throw new Error("تم الدخول ولكن لم يتم استلام مفتاح التوثيق (Token) من الخادم.");
        }

    } catch (err) {
        loginError.innerText = err.message;
        loginError.classList.remove("hidden");
    }
});

// ==========================================
// 4. إرسال الأوامر المحاسبية مع الـ Bearer Token
// ==========================================
sendBtn.addEventListener("click", sendMessage);
userInput.addEventListener("keypress", (e) => {
    if (e.key === "Enter") sendMessage();
});

function appendMessage(sender, text) {
    const messageDiv = document.createElement("div");
    messageDiv.classList.add("message", sender === "user" ? "user-message" : "bot-message");
    messageDiv.innerText = text;
    chatBox.appendChild(messageDiv);
    chatBox.scrollTop = chatBox.scrollHeight; 
}

async function sendMessage() {
    const text = userInput.value.trim();
    const file = fileInput.files[0];
    const token = localStorage.getItem("bob2_token");

    if (!token) {
        alert("جلسة العمل انتهت، يرجى إعادة تسجيل الدخول.");
        showLoginScreen();
        return;
    }

    if (!text && !file) return;

    if (text) appendMessage("user", text);
    if (file) appendMessage("user", `📁 تم إرفاق ملف: ${file.name}`);

    userInput.value = "";
    fileInput.value = "";

    const formData = new FormData();
    if (text) formData.append("prompt", text);
    if (file) formData.append("file", file);

    appendMessage("bot", "⏳ جاري المعالجة...");
    const loadingMessage = chatBox.lastChild;

    try {
        const response = await fetch(CHAT_URL, {
            method: "POST",
            headers: {
                "Authorization": `Bearer ${token}`
            },
            body: formData
        });

        if (response.status === 401) {
            localStorage.removeItem("bob2_token");
            throw new Error("انتهت صلاحية الجلسة، يرجى تسجيل الدخول مجدداً.");
        }

        if (!response.ok) {
            throw new Error(`واجه الخادم مشكلة (رمز الخطأ: ${response.status})`);
        }

        const data = await response.json();
        chatBox.removeChild(loadingMessage);

        const botReply = data.reply || data.message || JSON.stringify(data);
        appendMessage("bot", botReply);

    } catch (error) {
        if (chatBox.contains(loadingMessage)) {
            chatBox.removeChild(loadingMessage);
        }
        appendMessage("bot", `❌ ${error.message}`);
        
        if (error.message.includes("401") || error.message.includes("صلاحية")) {
            showLoginScreen();
        }
    }
}
