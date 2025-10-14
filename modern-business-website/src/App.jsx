import React from 'react'
import { Route, Routes } from 'react-router-dom'
import Home from './pages/Home'
import GettingStarted from './pages/GettingStarted'
import Header from './components/Header'

function App() {
  return (
    <>
      <Header />
      <Routes>
        <Route path='/' element={<Home />} />
        <Route path='/onboard' element={<GettingStarted />} />
      </Routes>
    </>

    )  
}

export default App