import ftplib

ftp = ftplib.FTP("prism.nacse.org")
ftp.login()

# See what's under time_series

print(ftp.nlst("/time_series/us/an/4km/tmean"))
print(ftp.nlst("/time_series/us/an/4km/tdmean"))