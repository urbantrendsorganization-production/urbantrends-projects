// MultiStepForm.jsx
import React, { useState, useRef } from "react";

/**
 * Multi-step order form for UrbanTrends
 * - Tailwind classes used (assumes Tailwind configured)
 * - Steps: 1) Contact  2) Services & Brief  3) Budget & Timeline  4) Review & Submit
 * - File uploads: up to 3 files, 5MB each
 * - Submit: POST to /api/order (FormData)
 */

const SERVICES = [
    "Website Development",
    "SEO & Digital Marketing",
    "UI/UX & Branding",
    "SaaS/Custom Software",
    "E-Commerce",
    "Maintenance & Support",
    "Consulting & Training",
    "Digital Products",
];

const BUDGETS = ["Under $500", "$500–$1,000", "$1,000–$5,000", "$5,000+"];
const TIMELINES = ["1–2 weeks", "1 month", "Flexible"];

export default function CustomForm() {
    const [step, setStep] = useState(1);
    const [submitting, setSubmitting] = useState(false);
    const [message, setMessage] = useState(null);
    const [errors, setErrors] = useState({});
    const fileInputRef = useRef();

    const [form, setForm] = useState({
        name: "",
        email: "",
        phone: "",
        services: [],
        description: "",
        budget: "",
        timeline: "",
        prefContact: "Email",
        referral: "",
        files: [],
    });

    const handleChange = (e) => {
        const { name, value, type, checked } = e.target;
        if (name === "services") {
            const val = value;
            setForm((p) => {
                const has = p.services.includes(val);
                return { ...p, services: has ? p.services.filter((s) => s !== val) : [...p.services, val] };
            });
            return;
        }
        setForm((p) => ({ ...p, [name]: value }));
    };

    const handleFileChange = (e) => {
        const files = Array.from(e.target.files).slice(0, 3);
        const tooBig = files.some((f) => f.size > 5 * 1024 * 1024);
        if (tooBig) {
            setErrors((p) => ({ ...p, files: "Each file must be ≤ 5MB" }));
            return;
        }
        setErrors((p) => ({ ...p, files: null }));
        setForm((p) => ({ ...p, files }));
    };

    const validateStep = (s) => {
        const newErrors = {};
        if (s === 1) {
            if (!form.name || form.name.trim().length < 2) newErrors.name = "Enter your full name";
            if (!form.email || !/^\S+@\S+\.\S+$/.test(form.email)) newErrors.email = "Valid email required";
        }
        if (s === 2) {
            if (!form.services.length) newErrors.services = "Pick at least one service";
            if (!form.description || form.description.trim().length < 20) newErrors.description = "Describe your project (20+ chars)";
        }
        if (s === 3) {
            if (!form.budget) newErrors.budget = "Pick a budget range";
            if (!form.timeline) newErrors.timeline = "Pick a timeline";
        }
        setErrors(newErrors);
        return Object.keys(newErrors).length === 0;
    };

    const nextStep = () => {
        if (validateStep(step)) {
            setStep((p) => Math.min(p + 1, 4));
        } else {
            window.scrollTo({ top: 0, behavior: "smooth" });
        }
    };
    const prevStep = () => {
        setErrors({});
        setStep((p) => Math.max(p - 1, 1));
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!validateStep(step)) return;
        setSubmitting(true);
        setMessage(null);
        try {
            const fd = new FormData();
            fd.append("name", form.name);
            fd.append("email", form.email);
            fd.append("phone", form.phone);
            fd.append("services", JSON.stringify(form.services));
            fd.append("description", form.description);
            fd.append("budget", form.budget);
            fd.append("timeline", form.timeline);
            fd.append("prefContact", form.prefContact);
            fd.append("referral", form.referral);
            form.files.forEach((f) => fd.append("files", f));
            const res = await fetch("/api/order", { method: "POST", body: fd });
            if (!res.ok) throw new Error("Network response not ok");
            await res.json();
            setMessage("Request sent — we’ll hit you up soon.");
            setForm({
                name: "",
                email: "",
                phone: "",
                services: [],
                description: "",
                budget: "",
                timeline: "",
                prefContact: "Email",
                referral: "",
                files: [],
            });
            if (fileInputRef.current) fileInputRef.current.value = "";
            setStep(1);
        } catch (err) {
            console.error(err);
            setMessage("Something broke — try again later.");
        } finally {
            setSubmitting(false);
        }
    };

    const progressPercent = ((step - 1) / (4 - 1)) * 100;

    return (
        <div className="">
            <form
                className=" sm:w-4/5 mx-auto bg-[#E2EAFC] p-6 rounded-lg shadow-md overflow-hidden"
                onSubmit={handleSubmit}
            >
                {/* HEADER / PROGRESS */}
                <div className="mb-6">
                    <div className="flex justify-between items-center text-sm text-gray-600 mb-2">
                        <div>Step {step} / 4</div>
                        <div className="font-medium">
                            {step === 1 ? "Contact" : step === 2 ? "Project" : step === 3 ? "Details" : "Review"}
                        </div>
                    </div>
                    <div className="w-full bg-black/40 h-2 rounded-full overflow-hidden">
                        <div className="h-2 rounded-full bg-black" style={{ width: `${progressPercent}%` }}></div>
                    </div>
                </div>

                {/* STEPS */}
                {step === 1 && (
                    <section>
                        <h3 className="text-xl font-semibold mb-4">Contact info</h3>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <label className="block">
                                <span className="text-sm font-medium">Full name *</span>
                                <input name="name" value={form.name} onChange={handleChange} className="mt-1 block w-full border border-black rounded px-3 py-2" placeholder="Jane Doe" />
                                {errors.name && <p className="text-red-500 text-sm mt-1">{errors.name}</p>}
                            </label>

                            <label className="block">
                                <span className="text-sm font-medium">Email *</span>
                                <input name="email" value={form.email} onChange={handleChange} className="mt-1 block w-full border border-black rounded px-3 py-2" placeholder="you@company.com" />
                                {errors.email && <p className="text-red-500 text-sm mt-1">{errors.email}</p>}
                            </label>

                            <label className="block md:col-span-2">
                                <span className="text-sm font-medium">Phone / WhatsApp (optional)</span>
                                <input name="phone" value={form.phone} onChange={handleChange} className="mt-1 block w-full border border-black rounded px-3 py-2" placeholder="+2547..." />
                            </label>
                        </div>
                    </section>
                )}

                {step === 2 && (
                    <section>
                        <h3 className="text-xl font-semibold mb-4">Project & Services</h3>

                        <div className="mb-4">
                            <span className="text-sm font-medium block mb-2">Which service(s) are you interested in? *</span>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                                {SERVICES.map((s) => (
                                    <label key={s} className="inline-flex items-center space-x-2">
                                        <input type="checkbox" name="services" value={s} checked={form.services.includes(s)} onChange={handleChange} className="form-checkbox h-5 w-5" />
                                        <span>{s}</span>
                                    </label>
                                ))}
                            </div>
                            {errors.services && <p className="text-red-500 text-sm mt-1">{errors.services}</p>}
                        </div>

                        <label className="block">
                            <span className="text-sm font-medium">Project description *</span>
                            <textarea name="description" value={form.description} onChange={handleChange} className="mt-1 block w-full border border-black rounded px-3 py-2" rows="5" placeholder="Features, goals, reference sites, target users..."></textarea>
                            {errors.description && <p className="text-red-500 text-sm mt-1">{errors.description}</p>}
                        </label>

                        <div className="mt-4">
                            <label className="block">
                                <span className="text-sm font-medium">Attachments (optional) — max 3 files, 5MB each</span>
                                <input ref={fileInputRef} type="file" multiple onChange={handleFileChange} className="mt-1" />
                                {errors.files && <p className="text-red-500 text-sm mt-1">{errors.files}</p>}
                                {form.files.length > 0 && (
                                    <ul className="mt-2 text-sm">
                                        {form.files.map((f, i) => (
                                            <li key={i}>
                                                {f.name} • {(f.size / 1024 / 1024).toFixed(2)} MB
                                            </li>
                                        ))}
                                    </ul>
                                )}
                            </label>
                        </div>
                    </section>
                )}

                {step === 3 && (
                    <section>
                        <h3 className="text-xl font-semibold mb-4">Budget & Timeline</h3>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <label className="block">
                                <span className="text-sm font-medium">Budget range *</span>
                                <select name="budget" value={form.budget} onChange={handleChange} className="mt-1 block w-full border border-black rounded px-3 py-2">
                                    <option value="">Choose</option>
                                    {BUDGETS.map((b) => (
                                        <option key={b} value={b}>
                                            {b}
                                        </option>
                                    ))}
                                </select>
                                {errors.budget && <p className="text-red-500 text-sm mt-1">{errors.budget}</p>}
                            </label>

                            <label className="block">
                                <span className="text-sm font-medium">Timeline *</span>
                                <select name="timeline" value={form.timeline} onChange={handleChange} className="mt-1 block w-full border border-black rounded px-3 py-2">
                                    <option value="">Choose</option>
                                    {TIMELINES.map((t) => (
                                        <option key={t} value={t}>
                                            {t}
                                        </option>
                                    ))}
                                </select>
                                {errors.timeline && <p className="text-red-500 text-sm mt-1">{errors.timeline}</p>}
                            </label>
                        </div>

                        <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
                            <label className="block">
                                <span className="text-sm font-medium">Preferred contact</span>
                                <select name="prefContact" value={form.prefContact} onChange={handleChange} className="mt-1 block w-full border border-black rounded px-3 py-2">
                                    <option>Email</option>
                                    <option>WhatsApp</option>
                                    <option>Call</option>
                                </select>
                            </label>

                            <label className="block">
                                <span className="text-sm font-medium">How did you hear about us? (optional)</span>
                                <input name="referral" value={form.referral} onChange={handleChange} className="mt-1 block w-full border border-black rounded px-3 py-2" placeholder="Google, Instagram, Friend..." />
                            </label>
                        </div>
                    </section>
                )}

                {step === 4 && (
                    <section>
                        <h3 className="text-xl font-semibold mb-4">Review & Submit</h3>
                        <div className="text-sm text-gray-800 space-y-2 mb-4">
                            <div><strong>Name:</strong> {form.name}</div>
                            <div><strong>Email:</strong> {form.email}</div>
                            {form.phone && <div><strong>Phone:</strong> {form.phone}</div>}
                            <div><strong>Services:</strong> {form.services.join(", ")}</div>
                            <div><strong>Budget:</strong> {form.budget}</div>
                            <div><strong>Timeline:</strong> {form.timeline}</div>
                            <div><strong>Description:</strong> <div className="mt-1 p-3 bg-gray-50 rounded">{form.description}</div></div>
                            {form.files.length > 0 && <div><strong>Attachments:</strong> {form.files.map((f) => f.name).join(", ")}</div>}
                        </div>

                        <label className="flex items-center space-x-2">
                            <input type="checkbox" checked readOnly className="form-checkbox" />
                            <span className="text-sm">I confirm the information above is correct.</span>
                        </label>
                    </section>
                )}

                {/* NAV */}
                <div className="mt-6 flex items-center justify-between">
                    <div>
                        {step > 1 && (
                            <button type="button" onClick={prevStep} className="px-4 py-2 border rounded">
                                Back
                            </button>
                        )}
                    </div>

                    <div>
                        {step < 4 ? (
                            <button type="button" onClick={nextStep} className="px-5 py-2 rounded bg-indigo-600 text-white font-medium">
                                Next
                            </button>
                        ) : (
                            <button type="submit" disabled={submitting} className="px-5 py-2 rounded bg-green-600 text-white font-medium">
                                {submitting ? "Sending..." : "Request a Quote"}
                            </button>
                        )}
                    </div>
                </div>

                {message && <p className="mt-4 text-sm">{message}</p>}
            </form>

            {/* footer
            <div className="mt-5">
                <Footer />
            </div> */}

        </div>

    );
}
