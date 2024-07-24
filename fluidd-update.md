# Update fluidd to v1.28.1
Source Reddit post: [The last working version of Fluidd at r/QIDI](https://www.reddit.com/r/QIDI/comments/1buinmx/the_last_working_version_of_fluidd/) by [u/billkenney](https://www.reddit.com/user/billkenney/)

![image](https://github.com/user-attachments/assets/fe6cc0a4-aaf9-42b4-947f-2594b70a6ad0)

Finally working ETA estimation, stepper temperatures, Z offset apply options, diagnostics feature, and A TON more! This is probably the most useful mod in this repo tbh, thanks billkenney!

## Installation
1. Download the fluidd archive file from the Google Drive link in this post: [Reddit](https://www.reddit.com/r/QIDI/comments/1buinmx/the_last_working_version_of_fluidd/)
2. Upload the fluidd file to the printer. The easiest way is to upload via the web interface:
![image](https://github.com/user-attachments/assets/b2ef4d60-3277-41ec-93f1-970778fa2ca0)
![image](https://github.com/user-attachments/assets/53648e1b-2572-43ac-8cd5-70fdc00dc8d0)
3. Use Terminal with PowerShell or any other ssh client, log in to the printer.
![image](https://github.com/user-attachments/assets/5d3207c7-b30a-4c6b-93c1-e413ca7032f1)
```
ssh root@192.168.x.x
```
If it asks for the fingerprint stuff, type in `yes`.\
The password is `makerbase`.
![image](https://github.com/user-attachments/assets/bf314ca1-cb12-4ffe-8623-bedb6865b5ab)
4. Back up the fluidd folder, let's copy it to the root home directory. It doesn't _really_ matter, nothing is gonna go wrong, right?
```
cd /home/mks
sudo cp -r fluidd ~/fluidd-bak
```
5. Copy the uploaded fluidd-1.28.tgz to the home directory.
```
cp klipper_config/fluidd-1.28.tgz fluidd.tgz
```
6. Delete the existing fluidd folder
```
rm -rf fluidd
```
7. Unpack fluidd.tgz
```
tar -xzf fluidd.tgz
```
8. Maybe reboot, maybe restart services. I didn't, and it worked fine.