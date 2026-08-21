"use client";

import Script from "next/script";
import { useEffect, useMemo, useState } from "react";

declare global {
  interface Window {
    google?: {
      translate?: {
        TranslateElement?: new (
          options: Record<string, unknown>,
          elementId: string,
        ) => unknown;
      };
    };
    googleTranslateElementInit?: () => void;
  }
}

const RTL_LANGS = new Set(["ar", "fa", "he", "iw", "ur", "ps", "sd", "ug", "yi"]);

const FEATURED_LANGUAGES = [
  ["en", "English"],
  ["es", "Español"],
  ["fr", "Français"],
  ["pt", "Português"],
  ["de", "Deutsch"],
  ["it", "Italiano"],
  ["nl", "Nederlands"],
  ["pl", "Polski"],
  ["ru", "Русский"],
  ["uk", "Українська"],
  ["tr", "Türkçe"],
  ["ar", "العربية"],
  ["he", "עברית"],
  ["fa", "فارسی"],
  ["ur", "اردو"],
  ["hi", "हिन्दी"],
  ["bn", "বাংলা"],
  ["pa", "ਪੰਜਾਬੀ"],
  ["gu", "ગુજરાતી"],
  ["ta", "தமிழ்"],
  ["te", "తెలుగు"],
  ["mr", "मराठी"],
  ["th", "ไทย"],
  ["vi", "Tiếng Việt"],
  ["id", "Bahasa Indonesia"],
  ["ms", "Bahasa Melayu"],
  ["tl", "Filipino"],
  ["zh-CN", "中文（简体）"],
  ["zh-TW", "中文（繁體）"],
  ["ja", "日本語"],
  ["ko", "한국어"],
  ["sw", "Kiswahili"],
  ["am", "አማርኛ"],
  ["ha", "Hausa"],
  ["yo", "Yorùbá"],
  ["zu", "isiZulu"],
  ["af", "Afrikaans"],
  ["ro", "Română"],
  ["el", "Ελληνικά"],
  ["cs", "Čeština"],
  ["hu", "Magyar"],
  ["sv", "Svenska"],
  ["da", "Dansk"],
  ["no", "Norsk"],
  ["fi", "Suomi"],
] as const;

const PREF_KEY = "sahjony-language";

function cookieLanguage(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/(?:^|;\s*)googtrans=\/en\/([^;]+)/);
  return match?.[1] ? decodeURIComponent(match[1]) : null;
}

function applyDirection(language: string) {
  const base = language.toLowerCase().split("-")[0];
  const rtl = RTL_LANGS.has(base);
  document.documentElement.lang = language || "en";
  document.documentElement.dir = rtl ? "rtl" : "ltr";
  document.body.dataset.translationDirection = rtl ? "rtl" : "ltr";
}

function setTranslationCookie(language: string) {
  const value = language === "en" ? "/en/en" : `/en/${language}`;
  document.cookie = `googtrans=${value};path=/;SameSite=Lax`;
  if (location.hostname.includes(".")) {
    document.cookie = `googtrans=${value};path=/;domain=.${location.hostname};SameSite=Lax`;
  }
}

export default function GlobalLanguageTranslation() {
  const [language, setLanguage] = useState("en");
  const [ready, setReady] = useState(false);

  const languageMap = useMemo(() => new Map(FEATURED_LANGUAGES), []);

  useEffect(() => {
    const persisted = localStorage.getItem(PREF_KEY);
    const cookie = cookieLanguage();
    const browser = navigator.language || "en";
    const browserBase = browser.split("-")[0];
    const supportedBrowser = FEATURED_LANGUAGES.some(([code]) => code === browser || code === browserBase)
      ? (FEATURED_LANGUAGES.some(([code]) => code === browser) ? browser : browserBase)
      : "en";
    const initial = persisted || cookie || supportedBrowser || "en";
    setLanguage(initial);
    applyDirection(initial);

    if (!persisted && !cookie && initial !== "en") {
      localStorage.setItem(PREF_KEY, initial);
      setTranslationCookie(initial);
    }

    window.googleTranslateElementInit = () => {
      const TranslateElement = window.google?.translate?.TranslateElement;
      if (!TranslateElement) return;
      new TranslateElement(
        {
          pageLanguage: "en",
          autoDisplay: false,
          multilanguagePage: true,
        },
        "sahjony-google-translate",
      );
      setReady(true);
    };

    return () => {
      delete window.googleTranslateElementInit;
    };
  }, []);

  useEffect(() => {
    if (!ready || language === "en") return;
    const select = document.querySelector<HTMLSelectElement>(".goog-te-combo");
    if (select && select.value !== language) {
      select.value = language;
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }, [ready, language]);

  const changeLanguage = (next: string) => {
    setLanguage(next);
    localStorage.setItem(PREF_KEY, next);
    setTranslationCookie(next);
    applyDirection(next);

    const googleSelect = document.querySelector<HTMLSelectElement>(".goog-te-combo");
    if (googleSelect) {
      googleSelect.value = next;
      googleSelect.dispatchEvent(new Event("change", { bubbles: true }));
      if (next === "en") window.location.reload();
      return;
    }

    window.location.reload();
  };

  return (
    <>
      <Script
        id="sahjony-worldwide-translation"
        src="https://translate.google.com/translate_a/element.js?cb=googleTranslateElementInit"
        strategy="afterInteractive"
      />

      <div id="sahjony-google-translate" aria-hidden="true" className="sahjonyGoogleTranslateSource" />

      <div className="sahjonyLanguageControl notranslate" translate="no">
        <span className="sahjonyLanguageIcon" aria-hidden="true">🌐</span>
        <label htmlFor="sahjony-language-select">Language</label>
        <select
          id="sahjony-language-select"
          aria-label="Choose application language"
          value={languageMap.has(language as never) ? language : "en"}
          onChange={(event) => changeLanguage(event.target.value)}
        >
          {FEATURED_LANGUAGES.map(([code, label]) => (
            <option key={code} value={code}>{label}</option>
          ))}
        </select>
      </div>

      <style jsx global>{`
        .sahjonyLanguageControl {
          position: fixed;
          right: max(14px, env(safe-area-inset-right));
          bottom: max(14px, env(safe-area-inset-bottom));
          z-index: 2147483000;
          display: flex;
          align-items: center;
          gap: 8px;
          min-height: 44px;
          padding: 7px 10px;
          border: 1px solid rgba(255,255,255,.16);
          border-radius: 999px;
          background: rgba(7,9,13,.94);
          color: #f2f5f9;
          box-shadow: 0 12px 36px rgba(0,0,0,.35);
          backdrop-filter: blur(14px);
          -webkit-backdrop-filter: blur(14px);
          font: 600 12px/1.2 Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
        }
        .sahjonyLanguageControl label { color: #9aa5b4; }
        .sahjonyLanguageIcon { font-size: 16px; }
        .sahjonyLanguageControl select {
          max-width: 156px;
          min-height: 34px;
          padding: 0 30px 0 10px;
          border: 1px solid rgba(255,255,255,.14);
          border-radius: 999px;
          background: #141a24;
          color: #f2f5f9;
          cursor: pointer;
        }
        .sahjonyGoogleTranslateSource {
          position: fixed !important;
          width: 1px !important;
          height: 1px !important;
          overflow: hidden !important;
          opacity: 0 !important;
          pointer-events: none !important;
        }
        .goog-te-banner-frame.skiptranslate,
        body > .skiptranslate { display: none !important; }
        body { top: 0 !important; }
        #goog-gt-tt, .goog-te-balloon-frame { display: none !important; }
        .goog-text-highlight { background: transparent !important; box-shadow: none !important; }
        html[dir="rtl"] .sahjonyLanguageControl {
          right: auto;
          left: max(14px, env(safe-area-inset-left));
        }
        @media (max-width: 640px) {
          .sahjonyLanguageControl label { display: none; }
          .sahjonyLanguageControl { padding: 6px 8px; }
          .sahjonyLanguageControl select { max-width: 132px; }
        }
        @media print {
          .sahjonyLanguageControl { display: none !important; }
        }
      `}</style>
    </>
  );
}
