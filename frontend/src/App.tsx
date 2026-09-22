import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import Layout from "@/components/Layout";
import BidCalculator from "@/pages/BidCalculator";
import BidDistribution from "@/pages/BidDistribution";
import DataOverview from "@/pages/DataOverview";
import ClientStatistics from "@/pages/ClientStatistics";
import RateDistribution from "@/pages/RateDistribution";
import DataCollection from "@/pages/DataCollection";
import Reference from "@/pages/Reference";
import NotFound from "@/pages/NotFound";

const queryClient = new QueryClient();

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <BrowserRouter future={{ v7_relativeSplatPath: true, v7_startTransition: true }}>
        <Routes>
          <Route element={<Layout />}>
            {/* 분포 기반 의사결정이 이 도구의 주 흐름이라 첫 화면으로 둔다 */}
            <Route path="/" element={<BidDistribution />} />
            <Route path="/calculator" element={<BidCalculator />} />
            {/* 기존 북마크 유지 */}
            <Route path="/bid-distribution" element={<Navigate to="/" replace />} />
            <Route path="/overview" element={<DataOverview />} />
            <Route path="/clients" element={<ClientStatistics />} />
            <Route path="/distribution" element={<RateDistribution />} />
            <Route path="/collection" element={<DataCollection />} />
            <Route path="/reference" element={<Reference />} />
          </Route>
          <Route path="*" element={<NotFound />} />
        </Routes>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
