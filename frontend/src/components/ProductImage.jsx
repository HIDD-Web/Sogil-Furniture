import React from "react";
import { imgUrl } from "../lib/api";
import { ImageOff } from "lucide-react";

export const ProductImage = ({ url, alt, className = "", ratio = "aspect-[4/3]" }) => {
  if (url) {
    return (
      <div className={`${ratio} w-full overflow-hidden bg-stone-100 ${className}`}>
        <img src={imgUrl(url)} alt={alt} loading="lazy" className="h-full w-full object-cover transition-transform duration-500 hover:scale-105" />
      </div>
    );
  }
  return (
    <div className={`${ratio} w-full flex flex-col items-center justify-center gap-2 bg-[#F1EBE0] text-[#8B7355] ${className}`} data-testid="product-image-placeholder">
      <ImageOff strokeWidth={1.5} size={28} />
      <span className="text-xs font-medium tracking-wide">Foto produk segera tersedia</span>
    </div>
  );
};

export default ProductImage;
