import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import Layout from "@/components/Layout";
import BidCalculator from "@/pages/BidCalculator";
import DataOverview from "@/pages/DataOverview";
import ClientStatistics from "@/pages/ClientStatistics";
import RateDistribution from "@/pages/RateDistribution";
import DataCollection from "@/pages/DataCollection";
import NotFound from "@/pages/NotFound";

const queryClient = new QueryClient();

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <BrowserRouter future={{ v7_relativeSplatPath: true, v7_startTransition: true }}>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<BidCalculator />} />
            <Route path="/overview" element={<DataOverview />} />
            <Route path="/clients" element={<ClientStatistics />} />
            <Route path="/distribution" element={<RateDistribution />} />
            <Route path="/collection" element={<DataCollection />} />
          </Route>
          <Route path="*" element={<NotFound />} />
        </Routes>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
