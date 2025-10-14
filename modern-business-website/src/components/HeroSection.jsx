import React from 'react'
import heroImg from '../assets/law.jpg'
import { useNavigate } from 'react-router-dom'

function HeroSection() {
    const navigate = useNavigate();
    return (
        <section className="w-full py-16 mt-3 p-2">
            <div className="container mx-auto flex md:flex-row items-center px-6 py-8 md:px-12 border-4 border-[#B6CCFE] rounded">
                {/* Text Content */}
                <div className="flex-1 mb-10 md:mb-0 md:mr-12">
                    {/* for who div */}


                    <h1 className="text-4xl md:text-6xl text-gray-900 mb-6 font-share-tech">
                        Welcome to Bloom Pay
                    </h1>
                    <p className="text-lg text-gray-700 mb-8">
                        Discover modern business solutions that elevate your brand and drive growth. We blend creativity, technology, and strategy to help you succeed in a fast-changing world.
                    </p>

                    <p><span className="text-sm text-gray-600 m-1"></span> <span className="font-semibold">Made for:</span></p>

                    <div className=' flex gap-2 mb-6'>
                        <div className="bg-[#C1D3FE] px-3 py-2 rounded-lg shadow-md flex flex-col items-center text-center border-2 border-black">
                            <span className="text-sm text-gray-600"></span> <span className="font-light">Students</span>
                        </div>
                        <div className="bg-[#C1D3FE] px-3 py-2 rounded-lg shadow-md flex flex-col items-center text-center border-2 border-black">
                            <span className="text-sm text-gray-600"></span> <span className="font-light">Professionals</span>
                        </div>
                        <div className="bg-[#C1D3FE] px-3 py-2 rounded-lg shadow-md flex flex-col items-center text-center border-2 border-black">
                            <span className="text-sm text-gray-600"></span> <span className="font-light">Businesses</span>
                        </div>
                    </div>


                    <button
                        onClick={() => navigate('/onboard')}
                        className="inline-block bg-gradient-to-r from-[#EDF2FB] to-[#C9D6FF] hover:bg-gradient-to-l text-black font-semibold py-3 px-8 rounded-lg shadow transition border-2 border-black duration-300 ease-in-out"
                    >
                        Get Started
                    </button>
                </div>
                {/* Image */}
                <div className="flex-1 flex justify-center">
                    <img
                        src={heroImg}
                        alt="UrbanTrends Hero"
                        className="w-full max-w-lg rounded-xl shadow-lg"
                    />
                </div>
            </div>
        </section>
    )
}

export default HeroSection