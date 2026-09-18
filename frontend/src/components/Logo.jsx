import React from "react";
import { imgUrl } from "../lib/api";
import { Armchair } from "lucide-react";

export const Logo = ({ size = 40, showText = true, logoUrl = "" }) => {
  return (
    <div className="flex items-center gap-2.5" data-testid="brand-logo">
      {logoUrl ? (
        <img src={imgUrl(logoUrl)} alt="Sogil Furniture" className="rounded-full object-cover ring-2 ring-[#E5DCC5]"
          style={{ width: size, height: size }} />
      ) : (
        <div className="flex items-center justify-center rounded-full bg-[#8B5A2B] text-[#F9F6F0] shrink-0 ring-2 ring-[#E5DCC5]"
          style={{ width: size, height: size }}>
          <Armchair strokeWidth={2} size={size * 0.52} />
        </div>
      )}
      {showText && (
        <div className="font-heading text-[#2C1E16] whitespace-nowrap text-base sm:text-lg font-bold">Sogil Furniture</div>
      )}
    </div>
  );
};

export default Logo;
