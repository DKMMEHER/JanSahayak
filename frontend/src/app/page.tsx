"use client";

import React, { useState, useEffect, useRef } from "react";
import {
  Mic,
  MicOff,
  Send,
  Upload,
  User,
  BookOpen,
  CheckCircle,
  FileText,
  Loader2,
  FileDown,
  TrendingUp,
  Sparkles,
  Volume2,
  Pencil,
  X,
  Save,
} from "lucide-react";



import { auth as firebaseAuth, RecaptchaVerifier, signInWithPhoneNumber } from "./firebase";
import { ConfirmationResult } from "firebase/auth";

const AUTH_PROVIDER = process.env.NEXT_PUBLIC_AUTH_PROVIDER || "local";
const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

interface Scheme {
  id: string;
  name_en: string;
  name_hi: string | null;
  description_en: string | null;
  description_hi: string | null;
  benefits: string | null;
  documents_required: string[] | null;
  application_url: string | null;
}

interface Message {
  role: "user" | "assistant";
  content: string;
  audioBlobUrl?: string;
}

/** Client-side script detection — mirrors backend detect_language(). */
function detectLang(text: string): string {
  const counts: Record<string, number> = {
    hindi: (text.match(/[\u0900-\u097F]/g) || []).length,
    bengali: (text.match(/[\u0980-\u09FF]/g) || []).length,
    punjabi: (text.match(/[\u0A00-\u0A7F]/g) || []).length,
    gujarati: (text.match(/[\u0A80-\u0AFF]/g) || []).length,
    odia: (text.match(/[\u0B00-\u0B7F]/g) || []).length,
    tamil: (text.match(/[\u0B80-\u0BFF]/g) || []).length,
    telugu: (text.match(/[\u0C00-\u0C7F]/g) || []).length,
    kannada: (text.match(/[\u0C80-\u0CFF]/g) || []).length,
    malayalam: (text.match(/[\u0D00-\u0D7F]/g) || []).length,
    urdu: (text.match(/[\u0600-\u06FF]/g) || []).length,
    english: (text.match(/[a-zA-Z]/g) || []).length,
  };

  let maxLang = "hindi";
  let maxCount = 0;
  let total = 0;

  for (const [lang, count] of Object.entries(counts)) {
    total += count;
    if (count > maxCount) {
      maxCount = count;
      maxLang = lang;
    }
  }

  if (total === 0) return "hindi";
  return maxLang;
}

export default function Dashboard() {
  // Authentication states
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<any>(null);
  const [showAuthModal, setShowAuthModal] = useState(false);
  const [isRegisterMode, setIsRegisterMode] = useState(false);
  const [authPhone, setAuthPhone] = useState("");
  const [authName, setAuthName] = useState("");
  const [authError, setAuthError] = useState("");
  const [authLoading, setAuthLoading] = useState(false);

  // Firebase OTP specific states
  const [confirmationResult, setConfirmationResult] = useState<ConfirmationResult | null>(null);
  const [otpCode, setOtpCode] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const recaptchaVerifierRef = useRef<any>(null);

  // Conversation & Profile states
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content:
        "नमस्ते! मैं जन सहायक हूँ। मैं आपको सरकारी योजनाओं की जानकारी पाने में मदद कर सकता हूँ। अपनी पात्रता जानने के लिए कृपया अपनी उम्र, कमाई, या व्यवसाय के बारे में बताएं।\n\nHello! I am Jan Sahayak. I can help you discover government welfare schemes. Please share your age, income, or occupation to get started.",
    },
  ]);
  const [profile, setProfile] = useState<Record<string, any>>({
    name: null,
    state: null,
    district: null,
    annual_income: null,
    occupation: null,
    category: null,
    family_size: null,
    age: null,
    gender: null,
  });

  const [matchedSchemes, setMatchedSchemes] = useState<Scheme[]>([]);
  const [textInput, setTextInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [language, setLanguage] = useState("hindi");
  const [playingAudioIdx, setPlayingAudioIdx] = useState<number | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // Document Digitization states
  const [isDigitizing, setIsDigitizing] = useState(false);
  const [digitizedDoc, setDigitizedDoc] = useState<string | null>(null);
  const [uploadStatus, setUploadStatus] = useState<string | null>(null);

  // Profile inline-editing state
  const [editingField, setEditingField] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");

  // Load token on mount
  useEffect(() => {
    const storedToken = localStorage.getItem("js_token");
    const storedUser = localStorage.getItem("js_user");
    if (storedToken && storedUser) {
      setToken(storedToken);
      const parsedUser = JSON.parse(storedUser);
      setUser(parsedUser);
      // Prepopulate profile from user details
      setProfile((prev) => ({
        ...prev,
        name: parsedUser.name || prev.name,
        state: parsedUser.state || prev.state,
        district: parsedUser.district || prev.district,
        annual_income: parsedUser.annual_income !== null ? parsedUser.annual_income : prev.annual_income,
        occupation: parsedUser.occupation || prev.occupation,
        category: parsedUser.category || prev.category,
        family_size: parsedUser.family_size !== null ? parsedUser.family_size : prev.family_size,
        age: parsedUser.age !== null ? parsedUser.age : prev.age,
        gender: parsedUser.gender || prev.gender,
      }));
    } else {
      setShowAuthModal(true);
    }
  }, []);

  // Authorized fetch helper — auto-handles expired tokens (401)
  const fetchWithAuth = async (url: string, options: RequestInit = {}) => {
    const storedToken = token || localStorage.getItem("js_token");
    const headers = {
      ...(options.headers || {}),
      ...(storedToken ? { "Authorization": `Bearer ${storedToken}` } : {}),
    };
    const res = await fetch(url, { ...options, headers });

    // If the token is expired/invalid, clear it and prompt re-login
    if (res.status === 401) {
      setToken(null);
      setUser(null);
      localStorage.removeItem("js_token");
      localStorage.removeItem("js_user");
      setShowAuthModal(true);
    }

    return res;
  };

  // Handle Register/Login submit
  const handleAuthSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!authPhone.trim()) {
      setAuthError("Please enter your mobile number.");
      return;
    }
    // Clean up input
    const cleanPhone = authPhone.trim();
    if (!/^\d{10}$/.test(cleanPhone)) {
      setAuthError("Please enter a valid 10-digit mobile number.");
      return;
    }

    setAuthError("");
    setAuthLoading(true);

    // Case A: Firebase Phone Authentication Flow
    if (AUTH_PROVIDER === "firebase") {
      try {
        if (!recaptchaVerifierRef.current) {
          recaptchaVerifierRef.current = new RecaptchaVerifier(firebaseAuth, "recaptcha-container", {
            size: "invisible",
            callback: () => {
              // reCAPTCHA solved
            }
          });
        }
        
        const phoneWithCountry = `+91${cleanPhone}`;
        const appVerifier = recaptchaVerifierRef.current;
        const confirmation = await signInWithPhoneNumber(firebaseAuth, phoneWithCountry, appVerifier);
        setConfirmationResult(confirmation);
        setOtpSent(true);
      } catch (err: any) {
        console.error("Firebase send OTP failed", err);
        setAuthError(err.message || "Failed to send OTP via Firebase. Verify configurations.");
      } finally {
        setAuthLoading(false);
      }
      return;
    }

    // Case B: Local Mock Authentication Flow (Default)
    try {
      const isRegister = isRegisterMode || !!authName.trim();
      const endpoint = isRegister ? "/api/auth/register" : "/api/auth/login";
      const payload = isRegister 
        ? { phone: cleanPhone, name: authName.trim() || `Citizen ${cleanPhone.slice(-4)}` } 
        : { phone: cleanPhone, otp: "1234" };

      const res = await fetch(`${BACKEND_URL}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Authentication failed. Please try again.");
      }

      const data = await res.json();
      setToken(data.access_token);
      setUser(data.user);
      localStorage.setItem("js_token", data.access_token);
      localStorage.setItem("js_user", JSON.stringify(data.user));
      setShowAuthModal(false);

      // Prepopulate profile from authenticated user details
      if (data.user) {
        setProfile((prev) => ({
          ...prev,
          name: data.user.name || prev.name,
          state: data.user.state || prev.state,
          district: data.user.district || prev.district,
          annual_income: data.user.annual_income !== null ? data.user.annual_income : prev.annual_income,
          occupation: data.user.occupation || prev.occupation,
          category: data.user.category || prev.category,
          family_size: data.user.family_size !== null ? data.user.family_size : prev.family_size,
          age: data.user.age !== null ? data.user.age : prev.age,
          gender: data.user.gender || prev.gender,
        }));
      }
    } catch (err: any) {
      setAuthError(err.message || "Something went wrong.");
    } finally {
      setAuthLoading(false);
    }
  };

  // Verify Firebase OTP submit
  const handleVerifyOtpSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!otpCode.trim() || otpCode.length < 6) {
      setAuthError("Please enter a valid 6-digit OTP code.");
      return;
    }

    if (!confirmationResult) {
      setAuthError("Session expired. Please request a new OTP code.");
      return;
    }

    setAuthError("");
    setAuthLoading(true);

    try {
      const result = await confirmationResult.confirm(otpCode);
      const idToken = await result.user.getIdToken();

      // Exchange ID token with our backend to sync/register user details
      const res = await fetch(`${BACKEND_URL}/api/auth/me`, {
        headers: { "Authorization": `Bearer ${idToken}` }
      });

      if (!res.ok) {
        throw new Error("Failed to synchronize user session with the database.");
      }

      const userData = await res.json();
      setToken(idToken);
      setUser(userData);
      localStorage.setItem("js_token", idToken);
      localStorage.setItem("js_user", JSON.stringify(userData));
      setShowAuthModal(false);

      // Prepopulate profile from authenticated user details
      setProfile((prev) => ({
        ...prev,
        name: userData.name || prev.name,
        state: userData.state || prev.state,
        district: userData.district || prev.district,
        annual_income: userData.annual_income !== null ? userData.annual_income : prev.annual_income,
        occupation: userData.occupation || prev.occupation,
        category: userData.category || prev.category,
        family_size: userData.family_size !== null ? userData.family_size : prev.family_size,
        age: userData.age !== null ? userData.age : prev.age,
        gender: userData.gender || prev.gender,
      }));
    } catch (err: any) {
      console.error("Firebase OTP verification failed", err);
      setAuthError("Invalid OTP code. Please check and try again.");
    } finally {
      setAuthLoading(false);
    }
  };

  // Handle Logout
  const handleLogout = () => {
    setToken(null);
    setUser(null);
    localStorage.removeItem("js_token");
    localStorage.removeItem("js_user");
    setConversationId(null);
    setMessages([
      {
        role: "assistant",
        content:
          "नमस्ते! मैं जन सहायक हूँ। मैं आपको सरकारी योजनाओं की जानकारी पाने में मदद कर सकता हूँ। अपनी पात्रता जानने के लिए कृपया अपनी उम्र, कमाई, या व्यवसाय के बारे में बताएं।\n\nHello! I am Jan Sahayak. I can help you discover government welfare schemes. Please share your age, income, or occupation to get started.",
      },
    ]);
    setProfile({
      name: null,
      state: null,
      district: null,
      annual_income: null,
      occupation: null,
      category: null,
      family_size: null,
      age: null,
      gender: null,
    });
    setMatchedSchemes([]);
    setShowAuthModal(true);
  };



  // Modal explanation state
  const [activeExplainScheme, setActiveExplainScheme] = useState<Scheme | null>(null);
  const [explanationText, setExplanationText] = useState("");
  const [isExplaining, setIsExplaining] = useState(false);
  const [activeGuideScheme, setActiveGuideScheme] = useState<Scheme | null>(null);
  const [guideText, setGuideText] = useState("");
  const [isGeneratingGuide, setIsGeneratingGuide] = useState(false);

  // ChatGPT/Gemini-style live voice transcription (Web Speech API)
  const [isRecording, setIsRecording] = useState(false);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recognitionRef = useRef<any>(null);
  const silenceTimerRef = useRef<NodeJS.Timeout | null>(null);
  const finalTranscriptRef = useRef("");

  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Load existing schemes list initially if profile isn't blank
  useEffect(() => {
    if (Object.values(profile).some((v) => v !== null)) {
      fetchMatches();
    }
  }, [profile]);

  const fetchMatches = async () => {
    try {
      // Find matches manually via API if profile has keys
      const activeKeys = Object.entries(profile)
        .filter(([_, v]) => v !== null)
        .reduce((acc, [k, v]) => ({ ...acc, [k]: v }), {});

      if (Object.keys(activeKeys).length === 0) return;

      const res = await fetchWithAuth(`${BACKEND_URL}/api/schemes/match`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(activeKeys),
      });
      if (res.ok) {
        const data = await res.json();
        setMatchedSchemes(data);
      }
    } catch (err) {
      console.error("Error fetching matches:", err);
    }
  };

  // Shared chat send logic (used by both text submit and voice auto-submit)
  // inputSource: "text" = text-only response, "voice" = text + TTS audio response
  const sendChatMessage = async (message: string, inputSource: "text" | "voice" = "text") => {
    if (!message.trim() || isLoading) return;

    setTextInput("");
    setMessages((prev) => [...prev, { role: "user", content: message }]);
    setIsLoading(true);

    // Detect language from the message text before sending
    const detectedLang = detectLang(message);
    setLanguage(detectedLang);

    try {
      const res = await fetchWithAuth(`${BACKEND_URL}/api/chat/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          conversation_id: conversationId,
          language: detectedLang,
          input_source: inputSource,
          profile_overrides: profile,
        }),
      });

      if (!res.ok) throw new Error("Chat request failed");

      const data = await res.json();
      setConversationId(data.conversation_id);
      setMessages((prev) => [...prev, { role: "assistant", content: data.reply }]);

      // Update language state from backend's auto-detection
      if (data.language) {
        setLanguage(data.language);
      }

      // Update profile variables from extracted context
      if (data.updated_profile) {
        setProfile((prev) => ({ ...prev, ...data.updated_profile }));
      }

      // Auto-play TTS audio only for voice input (ChatGPT-style)
      if (inputSource === "voice" && data.audio_base64) {
        try {
          const byteChars = atob(data.audio_base64);
          const byteArray = new Uint8Array(byteChars.length);
          for (let i = 0; i < byteChars.length; i++) {
            byteArray[i] = byteChars.charCodeAt(i);
          }
          const blob = new Blob([byteArray], { type: "audio/wav" });
          const blobUrl = URL.createObjectURL(blob);
          const snd = new Audio(blobUrl);

          // Attach to message so user can replay if autoplay is blocked
          setMessages((prev) => {
            const updated = [...prev];
            updated[updated.length - 1] = { ...updated[updated.length - 1], audioBlobUrl: blobUrl };
            return updated;
          });

          snd.play().catch((e) => console.warn("Autoplay blocked by browser:", e));
        } catch (audioErr) {
          console.error("Audio playback error:", audioErr);
        }
      }

      if (data.matched_schemes && data.matched_schemes.length > 0) {
        setMatchedSchemes(data.matched_schemes);
      }
    } catch (err) {
      console.error("Chat error:", err);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "क्षमा करें, सर्वर से जुड़ने में समस्या आ रही है। कृपया पुनः प्रयास करें।",
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  // Text Chat submit — text-only response (no TTS)
  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!textInput.trim() || isLoading) return;
    await sendChatMessage(textInput.trim(), "text");
  };

  const fetchCurrentProfile = async (convId: string) => {
    // Profile variables are extracted from chat responses automatically.
    // The chat API returns matched_schemes which implies profile context was recognized.
    // No separate GET endpoint exists — profile is updated via conversation context.
  };

  // ChatGPT/Gemini-style live voice transcription → auto-submit
  const handleVoiceRecord = () => {
    if (isRecording) {
      // Stop recognition — onend handler will auto-submit
      recognitionRef.current?.stop();
      return;
    }

    // Check browser support
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "आपका ब्राउज़र Speech Recognition सपोर्ट नहीं करता। कृपया Google Chrome उपयोग करें।" },
      ]);
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    // Dynamically set recognition language based on detected/active language
    const langCodeMap: Record<string, string> = {
      hindi: "hi-IN", english: "en-IN", bengali: "bn-IN", tamil: "ta-IN",
      telugu: "te-IN", marathi: "mr-IN", gujarati: "gu-IN", kannada: "kn-IN",
      malayalam: "ml-IN", odia: "or-IN", punjabi: "pa-IN", assamese: "as-IN", urdu: "ur-IN",
    };
    recognition.lang = langCodeMap[language] || "hi-IN";
    recognition.maxAlternatives = 1;

    recognitionRef.current = recognition;
    finalTranscriptRef.current = "";

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    recognition.onresult = (event: any) => {
      let interimText = "";
      let finalText = "";
      for (let i = 0; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          finalText += transcript + " ";
        } else {
          interimText += transcript;
        }
      }
      finalTranscriptRef.current = finalText;
      // Show live transcription in the text input
      setTextInput((finalText + interimText).trim());

      // Reset silence timer — auto-submit after 2s of silence
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = setTimeout(() => {
        recognition.stop();
      }, 1000);
    };

    recognition.onend = () => {
      setIsRecording(false);
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);

      // Auto-submit with voice source — response will include TTS audio
      const finalText = finalTranscriptRef.current.trim();
      if (finalText) {
        sendChatMessage(finalText, "voice");
      }
    };

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    recognition.onerror = (event: any) => {
      console.warn("Speech recognition error:", event.error);
      setIsRecording(false);

      const errorMessages: Record<string, string> = {
        "not-allowed": "Microphone access denied. Please allow microphone permission in your browser settings.",
        "permission-denied": "Microphone access denied. Please allow microphone permission in your browser settings.",
        "network": "Speech recognition requires internet. Please check your connection and try again.",
        "no-speech": "No speech detected. Please tap the mic and speak clearly.",
        "audio-capture": "No microphone found. Please connect a microphone and try again.",
        "aborted": "", // User cancelled — no message needed
      };

      const msg = errorMessages[event.error];
      if (msg) {
        setMessages((prev) => [...prev, { role: "assistant", content: msg }]);
      }
    };

    recognition.start();
    setIsRecording(true);
    setTextInput(""); // Clear for fresh transcription
  };

  // Document upload and digitize
  const handleDocumentUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsDigitizing(true);
    setUploadStatus("Uploading & digitizing...");

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetchWithAuth(`${BACKEND_URL}/api/schemes/digitize`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        const detail = errBody.detail || errBody.error || `Server error (${res.status})`;
        throw new Error(detail);
      }

      const data = await res.json();

      if (data.error) {
        throw new Error(data.error);
      }

      setDigitizedDoc(file.name);
      setUploadStatus("Success! Profile details extracted.");

      // Merge digitized details directly to profile
      const extracted = data.extracted_data || {};
      console.log("📄 Document extraction response:", data);
      console.log("✅ Extracted fields:", extracted);
      setProfile((prev) => {
        const updated = { ...prev };
        Object.keys(updated).forEach((key) => {
          if (extracted[key] !== undefined && extracted[key] !== null) {
            updated[key] = extracted[key];
          }
        });
        console.log("🔄 Updated profile:", updated);
        return updated;
      });
    } catch (err: any) {
      console.error("Upload error:", err);
      setUploadStatus(err?.message || "Error processing document. Try another file.");
    } finally {
      setIsDigitizing(false);
    }
  };

  // Explain scheme click
  const handleExplainClick = async (scheme: Scheme) => {
    setActiveExplainScheme(scheme);
    setExplanationText("");
    setIsExplaining(true);

    try {
      const res = await fetchWithAuth(`${BACKEND_URL}/api/schemes/${scheme.id}/explain?language=${language}`);
      if (!res.ok) throw new Error("Explanation failed");
      const data = await res.json();
      setExplanationText(data.explanation);
    } catch (err) {
      setExplanationText("विवरण प्राप्त करने में त्रुटि हुई। कृपया पुनः प्रयास करें।");
    } finally {
      setIsExplaining(false);
    }
  };

  // Application Guide click
  const handleGuideClick = async (scheme: Scheme) => {
    setActiveGuideScheme(scheme);
    setGuideText("");
    setIsGeneratingGuide(true);

    try {
      // Pass current profile context if filled to personalize it
      const res = await fetchWithAuth(`${BACKEND_URL}/api/schemes/${scheme.id}/guide?language=${language}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(profile),
      });
      if (!res.ok) throw new Error("Guide generation failed");
      const data = await res.json();
      setGuideText(data.guide);
    } catch (err) {
      setGuideText("आवेदन निर्देश तैयार करने में समस्या हुई। कृपया पुनः प्रयास करें।");
    } finally {
      setIsGeneratingGuide(false);
    }
  };



  return (
    <div className="flex-1 flex flex-col max-h-screen">
      {/* Header */}
      <header className="glass border-b border-white/5 px-6 py-4 flex items-center justify-between z-10 shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-orange-500 to-amber-500 flex items-center justify-center shadow-lg shadow-orange-500/20">
            <Sparkles className="w-5 h-5 text-white animate-pulse" />
          </div>
          <div>
            <h1 className="font-bold text-lg leading-tight tracking-wide flex items-center gap-2">
              Jan Sahayak <span className="text-orange-500 font-normal">जन सहायक</span>
            </h1>
            <p className="text-xs text-slate-400">Sovereign AI Welfare Finder</p>
          </div>
        </div>

        <div className="flex items-center gap-4">
          {user && (
            <div className="flex items-center gap-3 bg-white/5 border border-white/10 px-3 py-1.5 rounded-xl">
              <User className="w-3.5 h-3.5 text-orange-400" />
              <span className="text-xs font-semibold text-slate-300">{user.name}</span>
              <button
                onClick={handleLogout}
                className="text-[10px] text-red-400 hover:text-red-350 bg-red-500/10 hover:bg-red-500/20 px-2 py-0.5 rounded-md border border-red-500/20 transition font-bold"
              >
                Logout
              </button>
            </div>
          )}

          <div className="flex items-center gap-2">
            <div className={`w-2.5 h-2.5 rounded-full ${isRecording ? "bg-teal-500 shadow-lg shadow-teal-500/50 animate-pulse" : "bg-green-500 shadow-lg shadow-green-500/50"}`} />
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
              {isRecording ? "Listening" : "Ready"}
            </span>
          </div>
        </div>
      </header>

      {/* Main Grid */}
      <main className="flex-1 grid grid-cols-1 lg:grid-cols-12 overflow-hidden gap-4 p-4">
        {/* Left Col: Profiling & Docs (4 cols) */}
        <section className="lg:col-span-3 flex flex-col gap-4 overflow-hidden h-full">
          {/* Profile card — editable inline */}
          <div className="glass-premium rounded-2xl p-5 flex flex-col gap-4 overflow-y-auto max-h-[55%]">
            <h2 className="text-sm font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
              <User className="w-4 h-4 text-orange-500" /> Profile Variables
            </h2>
            <div className="space-y-2.5">
              {Object.entries(profile).map(([key, val]) => {
                const isEditing = editingField === key;
                const label = key.replace(/_/g, " ");
                const isDropdown = key === "category" || key === "gender";
                const isNumber = key === "annual_income" || key === "age" || key === "family_size";

                return (
                  <div key={key} className="border-b border-white/5 pb-2">
                    <div className="flex justify-between items-center text-sm">
                      <span className="text-slate-400 capitalize">{label}</span>
                      {isEditing ? (
                        <div className="flex items-center gap-1.5">
                          {isDropdown ? (
                            <select
                              autoFocus
                              value={editValue}
                              onChange={(e) => setEditValue(e.target.value)}
                              className="bg-slate-800 border border-orange-500/40 text-slate-200 text-xs rounded-lg px-2 py-1 focus:outline-none w-28"
                            >
                              <option value="">Select</option>
                              {key === "category" && (
                                <>
                                  <option value="SC">SC</option>
                                  <option value="ST">ST</option>
                                  <option value="OBC">OBC</option>
                                  <option value="General">General</option>
                                </>
                              )}
                              {key === "gender" && (
                                <>
                                  <option value="male">Male</option>
                                  <option value="female">Female</option>
                                </>
                              )}
                            </select>
                          ) : (
                            <input
                              autoFocus
                              type={isNumber ? "number" : "text"}
                              value={editValue}
                              onChange={(e) => setEditValue(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") {
                                  const finalVal = isNumber && editValue ? Number(editValue) : (editValue || null);
                                  setProfile((prev) => ({ ...prev, [key]: finalVal }));
                                  setEditingField(null);
                                } else if (e.key === "Escape") {
                                  setEditingField(null);
                                }
                              }}
                              className="bg-slate-800 border border-orange-500/40 text-slate-200 text-xs rounded-lg px-2 py-1 focus:outline-none w-28"
                            />
                          )}
                          <button
                            onClick={() => {
                              const finalVal = isNumber && editValue ? Number(editValue) : (editValue || null);
                              setProfile((prev) => ({ ...prev, [key]: finalVal }));
                              setEditingField(null);
                            }}
                            className="text-green-400 hover:text-green-300 p-0.5 transition"
                            title="Save"
                          >
                            <Save className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={() => setEditingField(null)}
                            className="text-slate-500 hover:text-slate-300 p-0.5 transition"
                            title="Cancel"
                          >
                            <X className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      ) : (
                        <div className="flex items-center gap-2">
                          <span className={`font-semibold ${(val !== null && val !== undefined) ? "text-teal-400" : "text-slate-600 italic text-xs"}`}>
                            {(val !== null && val !== undefined) ? (key === "annual_income" ? `₹${val.toLocaleString("en-IN")}` : val) : "Empty"}
                          </span>
                          <button
                            onClick={() => {
                              setEditingField(key);
                              setEditValue((val !== null && val !== undefined) ? String(val) : "");
                            }}
                            className="text-slate-600 hover:text-orange-400 p-0.5 transition"
                            title={`Edit ${label}`}
                          >
                            <Pencil className="w-3 h-3" />
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Document Upload card */}
          <div className="glass rounded-2xl p-5 flex-1 flex flex-col justify-between min-h-[40%]">
            <div className="flex flex-col gap-3">
              <h2 className="text-sm font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
                <FileText className="w-4 h-4 text-teal-400" /> Digitization Center
              </h2>
              <p className="text-xs text-slate-400 leading-relaxed">
                Upload your Aadhaar card, PAN card, or Income certificate to automatically fill your profile details.
              </p>
            </div>

            <div className="mt-4 flex-1 border border-dashed border-white/10 hover:border-orange-500/40 rounded-xl flex flex-col items-center justify-center p-4 text-center cursor-pointer transition relative hover:bg-white/5">
              <input
                type="file"
                accept="image/*,application/pdf"
                onChange={handleDocumentUpload}
                disabled={isDigitizing}
                className="absolute inset-0 opacity-0 cursor-pointer"
              />
              {isDigitizing ? (
                <div className="flex flex-col items-center gap-3">
                  <Loader2 className="w-8 h-8 text-orange-500 animate-spin" />
                  <span className="text-xs text-orange-400 font-medium">Processing via Sarvam Vision...</span>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-2.5">
                  <div className="w-10 h-10 rounded-full bg-white/5 flex items-center justify-center">
                    <Upload className="w-5 h-5 text-slate-300" />
                  </div>
                  <div>
                    <span className="text-xs font-semibold text-slate-200">Drag or Click to Upload</span>
                    <p className="text-[10px] text-slate-500 mt-1">PDF, JPG, PNG (Max 5MB)</p>
                  </div>
                </div>
              )}
            </div>

            {uploadStatus && (
              <div className="mt-3 text-xs bg-slate-800/50 p-2.5 rounded-lg border border-white/5 flex items-center gap-2 text-slate-300">
                <CheckCircle className="w-3.5 h-3.5 text-green-400 shrink-0" />
                <span className="truncate">{uploadStatus}</span>
              </div>
            )}
          </div>
        </section>

        {/* Middle Col: Assistant Area (5 cols) */}
        <section className="lg:col-span-5 glass-premium rounded-2xl flex flex-col overflow-hidden h-full">
          {/* Voice UI Header */}
          <div className="bg-slate-900/40 border-b border-white/5 p-4 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div
                className={`w-9 h-9 rounded-lg flex items-center justify-center ${isRecording ? "bg-teal-500 shadow-lg shadow-teal-500/20" : "bg-white/5"
                  }`}
              >
                <Mic className={`w-4 h-4 ${isRecording ? "text-white animate-pulse" : "text-slate-400"}`} />
              </div>
              <div>
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Conversational Assistant</span>
                <p className="text-[10px] text-slate-500 leading-none">Powered by Sarvam Sovereign AI</p>
              </div>
            </div>
            {!isRecording && (
              <select
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                className="bg-slate-800/80 hover:bg-slate-850 border border-white/10 hover:border-white/20 text-slate-200 text-xs rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-orange-500/50 cursor-pointer font-medium transition"
              >
                <option value="hindi">Hindi (हिंदी)</option>
                <option value="english">English</option>
                <option value="bengali">Bengali (বাংলা)</option>
                <option value="tamil">Tamil (தமிழ்)</option>
                <option value="telugu">Telugu (తెలుగు)</option>
                <option value="marathi">Marathi (मराठी)</option>
                <option value="gujarati">Gujarati (ગુજરાતી)</option>
                <option value="kannada">Kannada (ಕನ್ನಡ)</option>
                <option value="malayalam">Malayalam (മലയാളം)</option>
                <option value="odia">Odia (ଓଡ଼ିଆ)</option>
                <option value="punjabi">Punjabi (ਪੰਜਾਬੀ)</option>
                <option value="assamese">Assamese (অসমীয়া)</option>
                <option value="urdu">Urdu (اردو)</option>
              </select>
            )}
            {isRecording && (
              <div className="flex items-center gap-2 bg-teal-500/10 border border-teal-500/20 px-3 py-1 rounded-lg text-xs text-teal-400 font-medium">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-teal-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-teal-500"></span>
                </span>
                Listening...
              </div>
            )}
          </div>

          {/* Text dialogue panel */}
          <div className="flex-1 overflow-y-auto p-5 space-y-4">
            {messages.map((msg, idx) => (
              <div key={idx} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                <div
                  className={`max-w-[85%] rounded-2xl p-4 text-sm leading-relaxed whitespace-pre-line ${msg.role === "user"
                    ? "bg-gradient-to-br from-orange-500 to-amber-500 text-white font-medium rounded-tr-none shadow-md shadow-orange-500/10"
                    : "bg-slate-800/60 border border-white/5 text-slate-200 rounded-tl-none"
                    }`}
                >
                  {msg.content}
                  {msg.role === "assistant" && msg.audioBlobUrl && (
                    <button
                      onClick={() => {
                        if (audioRef.current) {
                          audioRef.current.pause();
                          audioRef.current = null;
                        }
                        const snd = new Audio(msg.audioBlobUrl!);
                        audioRef.current = snd;
                        setPlayingAudioIdx(idx);
                        snd.onended = () => { setPlayingAudioIdx(null); audioRef.current = null; };
                        snd.play().catch((e) => { console.warn("Playback failed:", e); setPlayingAudioIdx(null); });
                      }}
                      className={`mt-2 flex items-center justify-center p-1.5 rounded-full transition-all ${playingAudioIdx === idx
                        ? "bg-teal-500/20 text-teal-300"
                        : "text-slate-400 hover:text-teal-300 hover:bg-teal-500/10"
                        }`}
                      title="Replay Audio"
                    >
                      <Volume2 className={`w-4 h-4 ${playingAudioIdx === idx ? "animate-pulse" : ""}`} />
                    </button>
                  )}
                </div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>

          {/* Input Footer — ChatGPT/Gemini style */}
          <form onSubmit={handleSendMessage} className="p-4 bg-slate-900/40 border-t border-white/5 flex gap-2 items-center shrink-0">
            {/* Live transcription text input — always visible, shows words in real-time */}
            <div className={`flex-1 relative ${isRecording ? "ring-2 ring-teal-500/50 rounded-xl" : ""
              }`}>
              <input
                type="text"
                value={textInput}
                onChange={(e) => setTextInput(e.target.value)}
                placeholder={isRecording ? "🎙️ Listening... (बोलिए, शब्द यहाँ दिखेंगे)" : "Type or tap 🎤 to speak (बोलें या लिखें...)"}
                className={`w-full bg-slate-800/40 border outline-none rounded-xl px-4 py-3 text-sm text-slate-200 transition-all ${isRecording
                  ? "border-teal-500/40 bg-teal-500/5 text-teal-100 placeholder:text-teal-400/60"
                  : "border-white/5 focus:border-orange-500/40"
                  }`}
                readOnly={isRecording}
              />
              {isRecording && (
                <div className="absolute right-3 top-1/2 -translate-y-1/2 flex items-center gap-1.5">
                  <span className="relative flex h-2.5 w-2.5">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-teal-400 opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-teal-500"></span>
                  </span>
                  <span className="text-[10px] text-teal-400 font-medium">LIVE</span>
                </div>
              )}
            </div>

            {/* Mic toggle button */}
            <button
              type="button"
              onClick={handleVoiceRecord}
              disabled={isLoading}
              className={`w-12 h-12 rounded-xl flex items-center justify-center transition-all shrink-0 active:scale-95 ${isRecording
                ? "bg-teal-500 hover:bg-teal-600 shadow-lg shadow-teal-500/30 text-white"
                : "bg-slate-800 hover:bg-slate-700 border border-white/10 text-teal-400 hover:text-teal-300"
                } disabled:opacity-50`}
              title={isRecording ? "Click to stop and send" : "Click to start speaking"}
            >
              {isRecording ? (
                <div className="relative">
                  <MicOff className="w-5 h-5" />
                  <span className="absolute -top-1 -right-1 flex h-2.5 w-2.5">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-white opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-white"></span>
                  </span>
                </div>
              ) : (
                <Mic className="w-5 h-5" />
              )}
            </button>

            {/* Send button */}
            <button
              type="submit"
              disabled={isLoading || !textInput.trim()}
              className="w-12 h-12 rounded-xl bg-orange-500 hover:bg-orange-600 disabled:bg-slate-800 text-white flex items-center justify-center transition shrink-0 active:scale-95 shadow-md shadow-orange-500/10"
            >
              {isLoading ? <Loader2 className="w-5 h-5 animate-spin" /> : <Send className="w-5 h-5" />}
            </button>
          </form>
        </section>

        {/* Right Col: Matches (4 cols) */}
        <section className="lg:col-span-4 flex flex-col gap-4 overflow-hidden h-full">
          <div className="glass rounded-2xl p-5 flex flex-col gap-4 h-full overflow-hidden">
            <div className="flex items-center justify-between shrink-0">
              <h2 className="text-sm font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
                <TrendingUp className="w-4 h-4 text-orange-500" /> Eligible Scheme Matches
              </h2>
              <span className="text-[10px] font-bold px-2 py-0.5 bg-orange-500/10 text-orange-400 rounded-full border border-orange-500/20">
                {matchedSchemes.length} Found
              </span>
            </div>

            <div className="flex-1 overflow-y-auto space-y-4 pr-1">
              {matchedSchemes.length === 0 ? (
                <div className="h-48 border border-dashed border-white/5 rounded-xl flex flex-col items-center justify-center text-center p-5 text-slate-500 gap-2">
                  <BookOpen className="w-8 h-8 opacity-40 text-orange-500" />
                  <p className="text-xs">No scheme matches found.</p>
                  <p className="text-[10px] text-slate-600 leading-normal max-w-[200px]">
                    Share profile details like state, annual income, and caste category to view recommendations.
                  </p>
                </div>
              ) : (
                matchedSchemes.map((scheme) => (
                  <div
                    key={scheme.id}
                    className="bg-slate-800/35 hover:bg-slate-850/45 border border-white/5 hover:border-orange-500/20 p-4 rounded-xl flex flex-col gap-3 transition"
                  >
                    <div>
                      <h3 className="font-bold text-sm text-slate-200">
                        {language === "hindi" && scheme.name_hi ? scheme.name_hi : scheme.name_en}
                      </h3>
                      <p className="text-[10px] text-orange-400 font-medium mt-1">
                        Benefits: {scheme.benefits || "Available"}
                      </p>
                    </div>

                    <p className="text-xs text-slate-400 leading-relaxed line-clamp-3">
                      {language === "hindi" && scheme.description_hi
                        ? scheme.description_hi
                        : scheme.description_en}
                    </p>

                    <div className="flex gap-2 mt-1">
                      <button
                        onClick={() => handleExplainClick(scheme)}
                        className="flex-1 py-1.5 rounded-lg border border-white/10 hover:border-orange-500/30 text-[11px] font-bold text-slate-300 hover:text-orange-400 transition"
                      >
                        Explain the Scheme
                      </button>
                      <button
                        onClick={() => handleGuideClick(scheme)}
                        className="flex-1 py-1.5 rounded-lg bg-orange-500/10 hover:bg-orange-500/25 border border-orange-500/20 text-[11px] font-bold text-orange-400 transition"
                      >
                        How to Apply
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </section>
      </main>

      {/* Explanation Modal */}
      {activeExplainScheme && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 z-50 animate-fade-in">
          <div className="glass-premium rounded-2xl max-w-lg w-full p-6 flex flex-col gap-4 border border-white/10">
            <div className="flex justify-between items-start">
              <div>
                <h3 className="font-bold text-base text-slate-200">
                  {language === "hindi" && activeExplainScheme.name_hi
                    ? activeExplainScheme.name_hi
                    : activeExplainScheme.name_en}
                </h3>
                <span className="text-[10px] text-slate-400">Scheme explanation simplified by Jan Sahayak</span>
              </div>
              <button
                onClick={() => setActiveExplainScheme(null)}
                className="text-slate-400 hover:text-white text-sm"
              >
                ✕
              </button>
            </div>

            <div className="max-h-[300px] overflow-y-auto text-sm leading-relaxed text-slate-300 bg-slate-900/40 p-4 rounded-xl border border-white/5">
              {isExplaining ? (
                <div className="flex items-center gap-2 justify-center py-6 text-slate-400">
                  <Loader2 className="w-5 h-5 animate-spin text-orange-500" />
                  <span>Simplifying scheme description...</span>
                </div>
              ) : (
                explanationText
              )}
            </div>

            <div className="flex justify-end mt-2">
              <button
                onClick={() => setActiveExplainScheme(null)}
                className="bg-orange-500 hover:bg-orange-600 text-white text-xs px-5 py-2 rounded-lg font-bold transition"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Application Guide Modal */}
      {activeGuideScheme && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 z-50 animate-fade-in">
          <div className="glass-premium rounded-2xl max-w-lg w-full p-6 flex flex-col gap-4 border border-white/10">
            <div className="flex justify-between items-start">
              <div>
                <h3 className="font-bold text-base text-slate-200">
                  How to Apply: {language === "hindi" && activeGuideScheme.name_hi
                    ? activeGuideScheme.name_hi
                    : activeGuideScheme.name_en}
                </h3>
                <span className="text-[10px] text-slate-400">Step-by-step guide personalized for your profile</span>
              </div>
              <button
                onClick={() => setActiveGuideScheme(null)}
                className="text-slate-400 hover:text-white text-sm"
              >
                ✕
              </button>
            </div>

            {/* Documents Required Section */}
            {activeGuideScheme.documents_required && activeGuideScheme.documents_required.length > 0 && (
              <div className="bg-teal-500/5 border border-teal-500/15 rounded-xl p-3">
                <h4 className="text-[11px] font-bold uppercase tracking-wider text-teal-400 mb-2 flex items-center gap-1.5">
                  <FileText className="w-3.5 h-3.5" /> Documents Required
                </h4>
                <ul className="space-y-1">
                  {activeGuideScheme.documents_required.map((doc, i) => (
                    <li key={i} className="flex items-center gap-2 text-xs text-slate-300">
                      <CheckCircle className="w-3 h-3 text-teal-500 shrink-0" />
                      {doc}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Steps from LLM */}
            <div className="max-h-[250px] overflow-y-auto text-sm leading-relaxed text-slate-300 bg-slate-900/40 p-4 rounded-xl border border-white/5">
              {isGeneratingGuide ? (
                <div className="flex items-center gap-2 justify-center py-6 text-slate-400">
                  <Loader2 className="w-5 h-5 animate-spin text-orange-500" />
                  <span>Generating application steps...</span>
                </div>
              ) : (
                <div className="whitespace-pre-line">{guideText}</div>
              )}
            </div>

            {/* Apply URL + Close */}
            <div className="flex items-center justify-between mt-1">
              {activeGuideScheme.application_url ? (
                <a
                  href={activeGuideScheme.application_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 bg-teal-500/15 hover:bg-teal-500/25 border border-teal-500/30 text-teal-400 hover:text-teal-300 text-xs px-4 py-2 rounded-lg font-bold transition"
                >
                  <FileDown className="w-3.5 h-3.5" />
                  Apply on Official Website ↗
                </a>
              ) : (
                <span />
              )}
              <button
                onClick={() => setActiveGuideScheme(null)}
                className="bg-orange-500 hover:bg-orange-600 text-white text-xs px-5 py-2 rounded-lg font-bold transition"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Authentication Modal */}
      {showAuthModal && (
        <div className="fixed inset-0 bg-black/85 backdrop-blur-md flex items-center justify-center p-4 z-50 animate-fade-in">
          <div className="glass-premium rounded-3xl max-w-md w-full p-8 flex flex-col gap-6 border border-white/10 shadow-2xl relative overflow-hidden">
            {/* Background glowing gradients */}
            <div className="absolute -top-16 -right-16 w-32 h-32 bg-orange-500/20 rounded-full blur-3xl pointer-events-none" />
            <div className="absolute -bottom-16 -left-16 w-32 h-32 bg-amber-500/20 rounded-full blur-3xl pointer-events-none" />

            <div className="text-center relative z-10">
              <div className="w-14 h-14 rounded-2xl bg-gradient-to-tr from-orange-500 to-amber-500 flex items-center justify-center shadow-xl shadow-orange-500/20 mx-auto mb-4">
                <Sparkles className="w-7 h-7 text-white" />
              </div>
              <h2 className="text-xl font-extrabold text-slate-100 tracking-wide">
                Welcome to Jan Sahayak
              </h2>
              <p className="text-xs text-slate-400 mt-1">
                Secure Citizen Portal for Welfare Scheme Access
              </p>
            </div>

            <form onSubmit={otpSent ? handleVerifyOtpSubmit : handleAuthSubmit} className="flex flex-col gap-4 relative z-10">
              {/* Invisible recaptcha container */}
              <div id="recaptcha-container"></div>

              {!otpSent ? (
                <>
                  {/* Phone input */}
                  <div className="flex flex-col gap-1.5">
                    <label className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
                      Mobile Number
                    </label>
                    <div className="relative">
                      <span className="absolute left-3.5 top-2.5 text-slate-400 text-xs font-semibold">+91</span>
                      <input
                        type="tel"
                        placeholder="Enter 10-digit mobile number"
                        value={authPhone}
                        onChange={(e) => setAuthPhone(e.target.value.replace(/\D/g, "").slice(0, 10))}
                        className="w-full bg-slate-900/60 border border-white/10 focus:border-orange-500/50 rounded-xl pl-12 pr-4 py-2.5 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-orange-500/30 transition"
                        disabled={authLoading}
                      />
                    </div>
                  </div>

                  {/* Name input (optional) */}
                  <div className="flex flex-col gap-1.5">
                    <div className="flex justify-between items-center">
                      <label className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
                        Full Name
                      </label>
                      <span className="text-[10px] text-slate-500 italic">Optional</span>
                    </div>
                    <input
                      type="text"
                      placeholder="Enter your name to register"
                      value={authName}
                      onChange={(e) => setAuthName(e.target.value)}
                      className="w-full bg-slate-900/60 border border-white/10 focus:border-orange-500/50 rounded-xl px-4 py-2.5 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-orange-500/30 transition"
                      disabled={authLoading}
                    />
                  </div>
                </>
              ) : (
                /* OTP Verification input */
                <div className="flex flex-col gap-1.5">
                  <label className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
                    Enter 6-digit OTP Code
                  </label>
                  <input
                    type="text"
                    placeholder="------"
                    value={otpCode}
                    onChange={(e) => setOtpCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                    className="w-full bg-slate-900/60 border border-white/10 focus:border-orange-500/50 rounded-xl px-4 py-2.5 text-center text-lg tracking-widest text-slate-200 placeholder-slate-650 focus:outline-none focus:ring-1 focus:ring-orange-500/30 transition font-bold"
                    disabled={authLoading}
                  />
                  <div className="flex justify-between items-center mt-1">
                    <span className="text-[10px] text-slate-400 font-medium">SMS sent to +91 {authPhone}</span>
                    <button
                      type="button"
                      onClick={() => {
                        setOtpSent(false);
                        setOtpCode("");
                      }}
                      className="text-[10px] text-orange-400 hover:text-orange-350 hover:underline font-bold"
                    >
                      Change Number
                    </button>
                  </div>
                </div>
              )}

              {authError && (
                <div className="bg-red-500/10 border border-red-500/20 text-red-400 text-xs rounded-xl p-3 text-center font-medium">
                  {authError}
                </div>
              )}

              <button
                type="submit"
                disabled={authLoading}
                className="w-full bg-gradient-to-r from-orange-500 to-amber-500 hover:from-orange-600 hover:to-amber-600 text-white rounded-xl py-3 text-xs font-extrabold tracking-wider uppercase shadow-lg shadow-orange-500/20 hover:shadow-orange-500/35 transition duration-200 flex items-center justify-center gap-2 mt-2"
              >
                {authLoading ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    {otpSent ? "Verifying..." : "Sending OTP..."}
                  </>
                ) : (
                  otpSent ? "Confirm OTP" : "Proceed to Portal"
                )}
              </button>
            </form>

            <div className="text-center text-[10px] text-slate-500 mt-2 relative z-10 leading-relaxed">
              By proceeding, you agree to our Terms of Service. Authentication uses local secure tokens and OTP protocols.
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
