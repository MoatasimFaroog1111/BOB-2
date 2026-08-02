// ==========================================
// 1. الإعدادات والمتغيرات الأساسية
// ==========================================
const BASE_URL = "https://bob-2-production.up.railway.app";
const LOGIN_URL = `${BASE_URL}/api/v1/auth/login`; // أو /api/v1/auth/token حسب المسار المعتمد في الباك إند
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

// التثبت التلقائي عند فتح الصفحة
document.addEventListener("DOMContentLoaded", () => {
    const savedToken = localStorage.getItem("bob2_token");
    if (savedToken) {
        showChatScreen();
    } else {
        showLoginScreen();
    }
});

function showLoginScreen() {
    loginScreen.style.display = "block";
    chatScreen.style.display = "none";
}

function showChatScreen() {
    loginScreen.style.display = "none";
    chatScreen.style.display = "block";
}

// تسجيل الخروج
logoutBtn.addEventListener("click", () => {
    localStorage.removeItem("bob2_token");
    showLoginScreen();
});

// ==========================================
// 3. دالة تسجيل الدخول (Fetch Auth Token)
// ==========================================
loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    loginError.style.display = "none";

    const username = usernameInput.value.trim();
    const password = passwordInput.value.trim();

    // تجهيز بيانات الدخول (FastAPI يتوقع عادة FormData مع OAuth2)
    const loginData = new FormData();
    loginData.append("username", username);
    loginData.append("password", password);

    try {
        const response = await fetch(LOGIN_URL, {
            method: "POST",
            body: loginData
            // ملاحظة: قد تحتاج لتغيير الجسد إلى JSON إذا كان الباك إند يتوقع JSON:
            // headers: { 'Content-Type': 'application/json' },
            // body: JSON.stringify({ username, password })
        });

        if (!response.ok) {
            throw new Error("اسم المستخدم أو كلمة المرور غير صحيحة");
        }

        const data = await response.json();
        const token = data.access_token || data.token;

        if (token) {
            // حفظ التوكن والانتقال للواجهة الرئيسية
            localStorage.setItem("bob2_token", token);
            showChatScreen();
        } else {
            throw new Error("لم يتم استلام التوكن من الخادم.");
        }

    } catch (err) {
        loginError.innerText = err.message;
        loginError.style.display = "block";
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
    if (file) appendMessage("user", `📁 ملف: ${file.name}`);

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
            throw new Error("انتهت صلاحية التوكن، يرجى تسجيل الدخول مجدداً.");
        }

        if (!response.ok) {
            throw new Error(`خطأ من الخادم (${response.status})`);
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
        if (error.message.includes("401") || error.message.includes("انتهت صلاحية")) {
            showLoginScreen();
        }
    }
}
