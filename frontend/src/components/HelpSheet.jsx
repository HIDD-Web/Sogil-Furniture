import React, { useState } from "react";
import {
  HelpCircle,
  Check,
  ShoppingBag,
  SlidersHorizontal,
  Tag,
  MessageCircle,
  Smartphone,
} from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
  SheetTrigger,
  SheetClose,
} from "./ui/sheet";
import { Button } from "./ui/button";
import { useLang } from "../context/LanguageContext";
import PwaInstallModal from "./PwaInstallModal";

const STEPS = [
  {
    icon: ShoppingBag,
    titleKey: "help.step1_title",
    descriptionKey: "help.step1_description",
  },
  {
    icon: ShoppingBag,
    titleKey: "help.step2_title",
    descriptionKey: "help.step2_description",
  },
  {
    icon: SlidersHorizontal,
    titleKey: "help.step3_title",
    descriptionKey: "help.step3_description",
  },
  {
    icon: Tag,
    titleKey: "help.step4_title",
    descriptionKey: "help.step4_description",
  },
  {
    icon: MessageCircle,
    titleKey: "help.step5_title",
    descriptionKey: "help.step5_description",
  },
];

export default function HelpSheet() {
  const { t } = useLang();
  const [pwaOpen, setPwaOpen] = useState(false);

  return (
    <Sheet>
      <SheetTrigger asChild>
        <button
          type="button"
          aria-label={t("help.aria_label")}
          data-testid="home-help-button"
          className="fixed bottom-20 right-4 sm:bottom-5 sm:right-5 z-40 flex h-12 w-12 items-center justify-center rounded-full border border-[#E5DCC5] bg-white text-[#8B5A2B] shadow-lg transition-transform hover:scale-105 focus:outline-none focus:ring-2 focus:ring-[#8B5A2B] focus:ring-offset-2"
        >
          <HelpCircle size={23} />
        </button>
      </SheetTrigger>

      <SheetContent
        side="bottom"
        className="max-h-[85vh] overflow-y-auto rounded-t-3xl border-[#E5DCC5] bg-[#F9F6F0] px-5 pb-7 pt-6 sm:mx-auto sm:max-w-xl"
      >
        <SheetHeader className="pr-8 text-left">
          <SheetTitle className="font-heading text-2xl font-bold text-[#2C1E16]">
            {t("help.title")}
          </SheetTitle>

          <SheetDescription className="text-sm leading-relaxed text-[#5C4A3D]">
            {t("help.description")}
          </SheetDescription>
        </SheetHeader>

        <div className="mt-6 space-y-4">
          {STEPS.map((step, index) => {
            const Icon = step.icon;

            return (
              <div
                key={`${step.titleKey}-${index}`}
                className="flex items-start gap-3"
                data-testid={`help-step-${index + 1}`}
              >
                <div className="relative flex shrink-0">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#EFE6D5] text-[#8B5A2B]">
                    <Icon size={19} />
                  </div>

                  {index < STEPS.length - 1 && (
                    <div className="absolute left-1/2 top-10 h-4 w-px -translate-x-1/2 bg-[#E5DCC5]" />
                  )}
                </div>

                <div className="pt-0.5">
                  <div className="text-sm font-semibold text-[#2C1E16]">
                    {index + 1}. {t(step.titleKey)}
                  </div>

                  <p className="mt-0.5 text-xs leading-relaxed text-[#5C4A3D]">
                    {t(step.descriptionKey)}
                  </p>
                </div>
              </div>
            );
          })}
        </div>

        <div className="mt-6 pt-4 border-t border-[#E5DCC5] space-y-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => setPwaOpen(true)}
            className="h-11 w-full rounded-xl border-[#8B5A2B]/40 bg-white text-sm font-semibold text-[#8B5A2B] hover:bg-[#FAF5EE]"
          >
            <Smartphone size={17} className="mr-2 text-[#8B5A2B]" />
            Pasang Aplikasi di Layar HP
          </Button>

          <SheetClose asChild>
            <Button
              type="button"
              data-testid="help-close-button"
              className="h-11 w-full rounded-xl bg-[#8B5A2B] text-sm font-semibold hover:bg-[#6B4423]"
            >
              <Check size={17} className="mr-2" />
              {t("help.done")}
            </Button>
          </SheetClose>
        </div>
      </SheetContent>

      <PwaInstallModal
        isOpen={pwaOpen}
        onClose={() => setPwaOpen(false)}
        mode="customer"
      />
    </Sheet>
  );
}