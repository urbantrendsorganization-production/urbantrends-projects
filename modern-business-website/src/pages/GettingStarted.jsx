import CustomForm from '@/components/CustomForm'
import React from 'react'

function GettingStarted() {
    const images = [
        { link: 'https://images.unsplash.com/photo-1511883040705-6011fad9edfc?ixlib=rb-4.1.0&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D&auto=format&fit=crop&q=80&w=1174' },
    ]
    return (
        <div className='w-full h-[800px] flex items-center gap-2 p-3'>
            {/* images div */}
            <div className='w-1/2 h-4/5 flex items-center relative'>
                {images.map((image, index) => (
                    <img
                        key={index}
                        src={image.link}
                        alt={`Image ${index + 1}`}
                        className="rounded-lg w-full h-full object-cover"
                    />
                ))}
                {/* Dark overlay */}
                <div className="absolute inset-0 bg-black opacity-50 rounded-lg pointer-events-none"></div>
            </div>

            {/* info div */}
            <div className='w-1/2 relative'>
                {/* glowing background element */}
                <div className="absolute inset-0 flex justify-center -z-10">
                    <div className="w-48 h-48 sm:w-64 sm:h-64 md:w-80 md:h-80 rounded-full bg-black/40 blur-3xl opacity-40 animate-pulse"></div>
                </div>
                <h1 className="text-4xl text-center bg-clip-text stroke-text">
                    To a new way of saving & investing
                </h1>

                <div className='mt-5 shadow-lg shadow-black/20 rounded-lg p-4 bg-[#D7E3FC] backdrop-blur'>
                    <CustomForm />
                </div>
                <h5 className='text-center text-gray-800 m-2'>Fill the following information, to get access <br /> to all the services of this site</h5>
                

            </div>
        </div>
    )
}

export default GettingStarted