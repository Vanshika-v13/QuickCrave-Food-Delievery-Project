import React from 'react';
import { ArrowRight, ShieldCheck, Truck } from 'lucide-react';
import { Link } from 'react-router-dom';
import ImagePlaceholder from './ImagePlaceholder';

const Hero = () => {
  const heroImage = "/images/HeroSection Image.png"; 

  return (
    <section className="relative min-h-[500px] md:min-h-[600px] lg:h-[calc(100vh-80px)] py-12 md:py-16 lg:py-0 flex items-center overflow-hidden bg-gradient-to-r from-orange-50 to-white">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 md:px-10 w-full">
        <div className="grid md:grid-cols-2 gap-10 md:gap-12 items-center">
          {/* Left Side */}
          <div className="space-y-6 text-center md:text-left flex flex-col items-center md:items-start">
            <div className="inline-flex items-center gap-2 bg-orange-100 text-[#ff6b00] px-3.5 py-1.5 rounded-full font-bold text-[10px] sm:text-[11px] uppercase tracking-wider">
              <span className="flex h-2 w-2 rounded-full bg-[#ff6b00]"></span>
              Fastest Food Delivery
            </div>
            
            <h1 className="text-3xl sm:text-4xl md:text-5xl lg:text-6xl font-black text-gray-800 leading-tight">
              Unlock Our Flavours – <br className="hidden sm:inline" />
              <span className="text-[#ff6b00]">Freshly Served</span> <br className="hidden sm:inline" />
              At Your Doorstep.
            </h1>
            
            <p className="text-sm md:text-base text-gray-500 max-w-lg leading-relaxed text-center md:text-left">
              Freshly prepared & delivered fast to your doorstep. Explore our authentic cuisines.
            </p>
            
            <div className="flex flex-col sm:flex-row items-center gap-4 pt-2 w-full sm:w-auto">
              <Link to="/menu" className="w-full sm:w-auto px-7 py-3.5 bg-[#ff6b00] hover:bg-[#e65c00] text-white rounded-2xl font-bold flex items-center justify-center gap-2 group transition-colors duration-200">
                Order Now
                <ArrowRight className="w-5 h-5" />
              </Link>
              <Link to="/menu" className="w-full sm:w-auto px-7 py-3.5 bg-white border border-gray-200 text-gray-700 hover:bg-gray-50 rounded-2xl font-bold text-center justify-center transition-colors duration-200">
                View Menu
              </Link>
            </div>
          </div>

          {/* Right Side */}
          <div className="relative mt-10 md:mt-0 flex justify-center items-center w-full max-w-md md:max-w-none mx-auto">
            {/* Circular Orange Background (No Blur/Pulse) */}
            <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[85%] h-[85%] sm:w-[80%] sm:h-[80%] bg-orange-100/50 rounded-full -z-10"></div>
            
            <div className="relative z-10 flex justify-center items-center w-full">
              {heroImage ? (
                <img 
                  src={heroImage} 
                  alt="QuickCrave Food" 
                  className="w-[75%] sm:w-[65%] md:w-[80%] lg:w-[85%] h-auto object-contain drop-shadow-xl max-h-[300px] sm:max-h-[380px] md:max-h-none"
                />
              ) : (
                <div className="bg-white/50 p-4 rounded-[2.5rem] shadow-xl border border-white/80">
                  <ImagePlaceholder 
                    className="w-full aspect-[4/3] rounded-[2rem] shadow-inner" 
                    text="QuickCrave Special" 
                  />
                </div>
              )}
              
              {/* Floating Polish Elements (No bounce/float) */}
              <div className="absolute -top-4 -right-2 sm:-top-6 sm:-right-6 bg-white p-3 sm:p-4 rounded-2xl shadow-lg hidden sm:block border border-gray-50 z-20">
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 sm:w-10 sm:h-10 bg-green-50 rounded-full flex items-center justify-center">
                    <ShieldCheck className="w-5 h-5 sm:w-6 sm:h-6 text-green-500" />
                  </div>
                  <div>
                    <p className="text-[9px] sm:text-[10px] font-black text-gray-800 uppercase">100% Safety</p>
                    <p className="text-[9px] sm:text-[10px] text-gray-500">Hygiene Certified</p>
                  </div>
                </div>
              </div>

              <div className="absolute -bottom-4 -left-2 sm:-bottom-6 sm:-left-6 bg-white p-3 sm:p-4 rounded-2xl shadow-lg hidden sm:block border border-gray-50 z-20">
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 sm:w-10 sm:h-10 bg-orange-50 rounded-full flex items-center justify-center">
                    <Truck className="w-5 h-5 sm:w-6 sm:h-6 text-[#ff6b00]" />
                  </div>
                  <div>
                    <p className="text-[9px] sm:text-[10px] font-black text-gray-800 uppercase">Super Fast</p>
                    <p className="text-[9px] sm:text-[10px] text-gray-500">Delivery in 30m</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};

export default Hero;
