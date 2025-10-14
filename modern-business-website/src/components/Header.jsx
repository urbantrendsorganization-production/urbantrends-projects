"use client"

import React, { useState } from "react"
import { Link } from "react-router-dom"
import { CircleCheckIcon, Flower2, MenuIcon, XIcon } from "lucide-react"

import {
  NavigationMenu,
  NavigationMenuContent,
  NavigationMenuItem,
  NavigationMenuLink,
  NavigationMenuList,
  NavigationMenuTrigger,
  navigationMenuTriggerStyle,
} from "@/components/ui/navigation-menu"

import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"
import AuthModal from "./AuthModal"

// Example data
const components = [
  { title: "Alert Dialog", href: "/alert", description: "Modal for alerts." },
  { title: "Progress", href: "/progress", description: "Task progress display." },
  { title: "Tooltip", href: "/tooltip", description: "Extra info on hover." },
]

export default function Header() {
  const [open, setOpen] = useState(false)
  const [isAuthOpen, setIsAuthOpen] = useState(false);

  return (
    <>
      <header className="sticky top-0 z-50 w-full border-b border-[#B6CCFE] backdrop-blur">
        <div className="container mx-auto flex h-16 items-center justify-between px-4">
          {/* Brand / Logo */}
          <Link to="/" className="flex items-center gap-2 font-semibold">
            <Flower2 className="h-8 w-8 text-primary " />
            <span className="text-xl">Bloom Pay</span>
          </Link>

          {/* Desktop Navigation */}
          <div className="hidden md:block text-lg">
            <NavigationMenu>
              <NavigationMenuList>
                <NavigationMenuItem>
                  <NavigationMenuLink asChild className={navigationMenuTriggerStyle()}>
                    <Link to="/">Home</Link>
                  </NavigationMenuLink>
                </NavigationMenuItem>

                <NavigationMenuItem>
                  <NavigationMenuTrigger>Groups</NavigationMenuTrigger>
                  <NavigationMenuContent>
                    <ul className="grid w-[300px] gap-2 p-2">
                      {components.map((item) => (
                        <ListItem key={item.title} title={item.title} href={item.href}>
                          {item.description}
                        </ListItem>
                      ))}
                    </ul>
                  </NavigationMenuContent>
                </NavigationMenuItem>

                <NavigationMenuItem>
                  <NavigationMenuTrigger>Finance</NavigationMenuTrigger>
                  <NavigationMenuContent>
                    <ul className="grid w-[300px] gap-2 p-2">
                      <ListItem
                        title="Beautifully Designed"
                        href="/design"
                      >
                        Crafted with attention to detail and aesthetics.
                      </ListItem>
                      <ListItem
                        title="Accessible"
                        href="/accessibility"
                      >
                        Built with accessibility in mind for all users.
                      </ListItem>
                      <ListItem
                        title="Dark Mode"
                        href="/dark-mode"
                      >
                        Seamless transition between light and dark themes.
                      </ListItem>
                      <ListItem
                        title="TypeScript"
                        href="/typescript"
                      >
                        Strongly typed for better developer experience.
                      </ListItem>
                    </ul>
                  </NavigationMenuContent>
                </NavigationMenuItem>

                <NavigationMenuItem>
                  <NavigationMenuLink asChild className={navigationMenuTriggerStyle()}>
                    <Link to="/docs">contact</Link>
                  </NavigationMenuLink>
                </NavigationMenuItem>
              </NavigationMenuList>
            </NavigationMenu>
          </div>

          {/* Desktop Right Side */}
          <div className="hidden md:flex items-center gap-4">
            {/* <Link
            to="/login"
            className="text-sm font-medium text-muted-foreground hover:text-foreground"
          >
            Login
          </Link> */}
            <button
              onClick={() => setIsAuthOpen(true)}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
              Sign Up
            </button>
          </div>

          {/* Mobile Menu Button */}
          <div className="md:hidden">
            <Sheet open={open} onOpenChange={setOpen}>
              <SheetTrigger asChild>
                <button className="rounded-md p-2 hover:bg-accent">
                  {open ? <XIcon className="h-5 w-5" /> : <MenuIcon className="h-5 w-5" />}
                </button>
              </SheetTrigger>
              <SheetContent side="right" className="w-[250px] p-4 bg-[#ABC4FF] backdrop-blur">
                <SheetHeader>
                  <SheetTitle>Menu</SheetTitle>
                </SheetHeader>
                <nav className="mt-6 flex flex-col gap-4">
                  <Link to="/" onClick={() => setOpen(false)} className="text-sm font-medium">
                    Home
                  </Link>
                  <Link
                    to="/components"
                    onClick={() => setOpen(false)}
                    className="text-sm font-medium"
                  >
                    Components
                  </Link>
                  <Link
                    to="/docs"
                    onClick={() => setOpen(false)}
                    className="text-sm font-medium"
                  >
                    Docs
                  </Link>
                  <div className="mt-4 border-t pt-4">
                    <Link
                      to="/login"
                      onClick={() => setOpen(false)}
                      className="block text-sm text-muted-foreground hover:text-foreground"
                    >
                      Login
                    </Link>
                    <Link
                      to="/signup"
                      onClick={() => setOpen(false)}
                      className="mt-2 inline-block rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
                    >
                      Sign Up
                    </Link>
                  </div>
                </nav>
              </SheetContent>
            </Sheet>
          </div>
        </div>
      </header>
      {/* Auth Modal */}
      <AuthModal isOpen={isAuthOpen} onClose={() => setIsAuthOpen(false)} />
    </>
  )
}




// Reusable list item for dropdowns
        function ListItem({title, children, href, ...props }) {
  return (
        <li {...props}>
          <NavigationMenuLink asChild>
            <Link
              to={href}
              className="block space-y-1 rounded-md p-2 hover:bg-accent focus:bg-accent"
            >
              <div className="text-sm font-medium leading-none">{title}</div>
              <p className="text-sm text-muted-foreground line-clamp-2">{children}</p>
            </Link>
          </NavigationMenuLink>
        </li>
        )
}
