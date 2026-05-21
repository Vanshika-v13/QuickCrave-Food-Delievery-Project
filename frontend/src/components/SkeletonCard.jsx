import React from 'react';

const SkeletonCard = () => {
  return (
    <div className="bg-white rounded-2xl overflow-hidden shadow-md border border-gray-100 animate-pulse">
      <div className="h-52 w-full bg-gray-200"></div>
      <div className="p-6 space-y-4">
        <div className="flex justify-between items-center">
          <div className="h-6 w-1/2 bg-gray-200 rounded"></div>
          <div className="h-6 w-1/4 bg-gray-200 rounded"></div>
        </div>
        <div className="space-y-2">
          <div className="h-4 w-full bg-gray-200 rounded"></div>
          <div className="h-4 w-2/3 bg-gray-200 rounded"></div>
        </div>
      </div>
    </div>
  );
};

export default SkeletonCard;
