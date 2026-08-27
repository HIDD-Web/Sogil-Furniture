import React, { createContext, useContext, useEffect, useState } from "react";
import { LANGS, translate } from "../lib/i18n";

const LanguageContext = createContext(null);

export const LanguageProvider = ({ children }) => {
  const [lang, setLang] = useState(() => localStorage.getItem("sogil_lang") || "id");

  useEffect(() => {
    localStorage.setItem("sogil_lang", lang);
    const cfg = LANGS.find((l) => l.code === lang) || LANGS[0];
    document.documentElement.lang = lang;
    document.documentElement.dir = cfg.dir;
  }, [lang]);

  const t = (key) => translate(lang, key);
  const dir = (LANGS.find((l) => l.code === lang) || LANGS[0]).dir;

  return (
    <LanguageContext.Provider value={{ lang, setLang, t, dir, langs: LANGS }}>
      {children}
    </LanguageContext.Provider>
  );
};

export const useLang = () => useContext(LanguageContext);
