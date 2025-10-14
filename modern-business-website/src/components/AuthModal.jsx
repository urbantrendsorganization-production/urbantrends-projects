import React, { useState } from 'react'

function AuthModal({ isOpen, onClose }) {
    const [isSignUp, setIsSignUp] = useState(false);

    if (!isOpen) return null;

    return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-xl p-8 w-[90%] max-w-md relative animate-fadeIn"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Close Button */}
        <button
          className="absolute top-3 right-3 text-gray-400 hover:text-gray-600"
          onClick={onClose}
        >
          ✕
        </button>

        {/* Header */}
        <h2 className="text-2xl font-bold text-center text-gray-800 mb-6">
          {isSignUp ? "Create an Account" : "Welcome Back"}
        </h2>

        

        {/* Form */}
        <form className="space-y-4">
          {isSignUp && (
            <input
              type="text"
              placeholder="Full Name"
              className="w-full p-3 border rounded-xl focus:ring-2 focus:ring-indigo-500 outline-none"
            />
          )}
          <input
            type="email"
            placeholder="Email"
            className="w-full p-3 border rounded-xl focus:ring-2 focus:ring-indigo-500 outline-none"
          />
          <input
            type="password"
            placeholder="Password"
            className="w-full p-3 border rounded-xl focus:ring-2 focus:ring-indigo-500 outline-none"
          />
          <button
            type="submit"
            className="w-full py-3 text-white bg-indigo-600 rounded-xl hover:bg-indigo-700 transition-all duration-300"
          >
            {isSignUp ? "Sign Up" : "Sign In"}
          </button>
        </form>

        {/* Divider */}
        <div className="flex items-center my-4">
          <hr className="flex-grow border-gray-300" />
          <span className="px-3 text-gray-400 text-sm">or</span>
          <hr className="flex-grow border-gray-300" />
        </div>

        {/* Social Logins */}
        <div className="space-y-3 mb-5">
          <button className="w-full flex items-center justify-center gap-3 border border-gray-300 rounded-xl py-2.5 hover:bg-gray-50 transition-all duration-200">
            <img src="https://www.svgrepo.com/show/475656/google-color.svg" alt="Google" className="w-5 h-5" />
            <span className="text-gray-700 font-medium">Continue with Google</span>
          </button>

          <button className="w-full flex items-center justify-center gap-3 border border-gray-300 rounded-xl py-2.5 hover:bg-gray-50 transition-all duration-200">
            <img src="https://www.svgrepo.com/show/448225/apple.svg" alt="Apple" className="w-5 h-5" />
            <span className="text-gray-700 font-medium">Continue with Apple</span>
          </button>

          <button className="w-full flex items-center justify-center gap-3 border border-gray-300 rounded-xl py-2.5 hover:bg-gray-50 transition-all duration-200">
            <img src="https://www.svgrepo.com/show/349375/github.svg" alt="GitHub" className="w-5 h-5" />
            <span className="text-gray-700 font-medium">Continue with GitHub</span>
          </button>
        </div>


        {/* Switch Mode */}
        <p className="text-center text-gray-500 mt-4 text-sm">
          {isSignUp ? (
            <>
              Already have an account?{" "}
              <button
                onClick={() => setIsSignUp(false)}
                className="text-indigo-600 hover:underline"
              >
                Sign in
              </button>
            </>
          ) : (
            <>
              Don’t have an account?{" "}
              <button
                onClick={() => setIsSignUp(true)}
                className="text-indigo-600 hover:underline"
              >
                Sign up
              </button>
            </>
          )}
        </p>
      </div>
    </div>
  );
}

export default AuthModal