import React from 'react'
import Header from '../components/Header'
import HeroSection from '@/components/HeroSection'

function Home() {
  return (
    <div className="w-full relative">
      

      {/* Hero section */}
      <div>
        <HeroSection />
      </div>

      {/* partners section */}
      <div className="w-full py-16 mt-3">
        <div className="container mx-auto">
          <h2 className="text-3xl font-bold text-center mb-8">Our Partners</h2>
          <div className="flex flex-wrap justify-center">
            {/* Partner logos go here */}
          </div>
        </div>
      </div>

    </div>
  )
}

export default Home
