import React from 'react';
import { ImageOff } from 'lucide-react';

const ImagePlaceholder = ({ className = "h-48", text = "Image Required" }) => {
  return (
    <div className={`bg-gray-200 flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-gray-300 ${className}`}>
      <ImageOff className="w-8 h-8 text-gray-400 mb-2" />
      <span className="text-gray-500 font-medium text-sm">{text}</span>
    </div>
  );
};

export default ImagePlaceholder;
