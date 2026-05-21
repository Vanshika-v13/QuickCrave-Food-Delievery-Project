import React from 'react';
import { Truck, ShieldCheck, Wallet, MapPin } from 'lucide-react';

const features = [
  {
    icon: Truck,
    title: "Fast Delivery",
    description: "Get your food delivered in less than 30 minutes at your doorstep."
  },
  {
    icon: ShieldCheck,
    title: "Hygienic Food",
    description: "We maintain the highest standards of hygiene in our kitchen."
  },
  {
    icon: Wallet,
    title: "Affordable Prices",
    description: "Delicious food at prices that won't break your bank."
  },
  {
    icon: MapPin,
    title: "Live Tracking",
    description: "Track your order in real-time from the kitchen to your door."
  }
];

const WhyChooseUs = () => {
  return (
    <section className="py-16 sm:py-20 bg-white">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 md:px-10">
        <div className="text-center mb-10 sm:mb-12">
          <h2 className="text-xs sm:text-sm font-black text-gray-500 uppercase tracking-[0.2em] mb-2">Service Highlights</h2>
          <h3 className="text-2xl sm:text-3xl font-black text-gray-800 tracking-tight">Why Choose Us?</h3>
        </div>
        
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 sm:gap-8">
          {features.map((feature, index) => (
            <div 
              key={index} 
              className="bg-white rounded-xl shadow-md p-6 sm:p-8 text-center border border-gray-50 hover:shadow-xl transition-all duration-300 hover:-translate-y-1 flex flex-col items-center h-full"
            >
              <div className="inline-flex items-center justify-center w-14 h-14 sm:w-16 sm:h-16 rounded-full bg-orange-50 mb-4 sm:mb-6 flex-shrink-0">
                <feature.icon className="w-7 h-7 sm:w-8 sm:h-8 text-[#ff6b00]" />
              </div>
              <h4 className="text-lg sm:text-xl font-bold text-gray-800 mb-2 sm:mb-3">{feature.title}</h4>
              <p className="text-gray-500 text-xs sm:text-sm leading-relaxed">
                {feature.description}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
};

export default WhyChooseUs;
